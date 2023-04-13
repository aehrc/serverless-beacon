from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
import threading
import urllib
import json
import time
import re

from smart_open import open as sopen
import requests
import boto3

from shared.dynamodb import OntoData, Ontology, Descendants, Anscestors
from shared.utils import ENV_ATHENA
from ctas_queries import QUERY as CTAS_TEMPLATE
from generate_query_index import QUERY as INDEX_QUERY
from generate_query_terms import QUERY as TERMS_QUERY
from generate_query_relations import QUERY as RELATIONS_QUERY


athena = boto3.client("athena")
s3 = boto3.client("s3")


ENSEMBL_OLS = "https://www.ebi.ac.uk/ols/api/ontologies"
ONTOSERVER = "https://r4.ontoserver.csiro.au/fhir/ValueSet/$expand"
ONTO_TERMS_QUERY = f""" SELECT term,tablename,colname,type,label FROM "{ENV_ATHENA.ATHENA_TERMS_TABLE}" """
INDEX_QUERY = INDEX_QUERY.format(
    table=ENV_ATHENA.ATHENA_TERMS_CACHE_TABLE,
    uri=f"s3://{ENV_ATHENA.ATHENA_METADATA_BUCKET}/terms-index/",
)
TERMS_QUERY = TERMS_QUERY.format(
    table=ENV_ATHENA.ATHENA_TERMS_CACHE_TABLE,
    uri=f"s3://{ENV_ATHENA.ATHENA_METADATA_BUCKET}/terms/",
)
RELATIONS_QUERY = RELATIONS_QUERY.format(
    uri=f"s3://{ENV_ATHENA.ATHENA_METADATA_BUCKET}/relations/",
    individuals_table=ENV_ATHENA.ATHENA_INDIVIDUALS_TABLE,
    biosamples_table=ENV_ATHENA.ATHENA_BIOSAMPLES_TABLE,
    runs_table=ENV_ATHENA.ATHENA_RUNS_TABLE,
    analyses_table=ENV_ATHENA.ATHENA_ANALYSES_TABLE,
)


def get_ontology_details(ontology):
    details = None
    try:
        details = Ontology.get(ontology)
    except Ontology.DoesNotExist:
        if ontology == "SNOMED":
            # use ontoserver
            details = Ontology(ontology.upper())
            details.data = json.dumps(
                {"id": "SNOMED", "baseUri": "http://snomed.info/sct"}
            )
            details.save()
        else:
            # use ENSEMBL
            if response := requests.get(f"{ENSEMBL_OLS}/{ontology}"):
                response_json = response.json()
                details = Ontology(ontology.upper())
                details.data = json.dumps(
                    {
                        "id": response_json["ontologyId"].upper(),
                        "baseUri": response_json["config"]["baseUris"][0],
                    }
                )
                details.save()

    # any other error must be raised
    return details


def get_ontologies_clusters():
    query = f'SELECT DISTINCT term FROM "{ENV_ATHENA.ATHENA_TERMS_TABLE}"'

    response = athena.start_query_execution(
        QueryString=query,
        QueryExecutionContext={"Database": ENV_ATHENA.ATHENA_METADATA_DATABASE},
        WorkGroup=ENV_ATHENA.ATHENA_WORKGROUP,
    )

    execution_id = response["QueryExecutionId"]
    await_result(execution_id)

    ontology_clusters = defaultdict(set)

    with sopen(
        f"s3://{ENV_ATHENA.ATHENA_METADATA_BUCKET}/query-results/{execution_id}.csv"
    ) as s3f:
        for n, line in enumerate(s3f):
            if n == 0:
                continue
            term = line.strip().strip('"')

            # beacon API does not allow non CURIE formatted terms
            # however, SNOMED appears are non-CURIE prefixed terms
            # following is to support that, however API will not ingest
            # always submit in form SNOMED:123212
            if re.match(r"(?i)(^SNOMED)|([0-9]+)", term):
                ontology = "SNOMED"
                ontology_clusters[ontology].add(term)
            else:
                ontology = term.split(":")[0]
                ontology_clusters[ontology].add(term)

    return ontology_clusters


# in future, there could be an issue when descendants entries exceed 400KB
# which means we would have roughtly 20480, 20 byte entries (unlikely?)
# this would also mean, our SQL queries would reach the 256KB limit
# we should be able to easily spread terms across multiple dynamodb
# entries and have multiple queries (as recommended by AWS)
def index_terms_tree():
    # START subroutines
    # subroutine for ensemble
    def threaded_request_ensemble(term, url):
        if response := requests.get(url):
            response_json = response.json()
            anscestors = set()
            for response_term in response_json["_embedded"]["terms"]:
                obo_id = response_term["obo_id"]
                if obo_id:
                    anscestors.add(obo_id)
            return (term, anscestors)
        else:
            print(f"Error fetching term from Ensembl OLS {term}")

    # subroutine for ontoserver
    def threaded_request_ontoserver(term, url):
        snomed = "SNOMED" in term.upper()
        retries = 1
        response = None
        while (not response or response.status_code != 200) and retries < 10:
            retries += 1
            response = requests.post(
                url,
                json={
                    "resourceType": "Parameters",
                    "parameter": [
                        {
                            "name": "valueSet",
                            "resource": {
                                "resourceType": "ValueSet",
                                "compose": {
                                    "include": [
                                        {
                                            "system": data["baseUri"],
                                            "filter": [
                                                {
                                                    "property": "concept",
                                                    "op": "generalizes",
                                                    "value": f"{term.replace('SNOMED:', '')}",
                                                }
                                            ],
                                        }
                                    ]
                                },
                            },
                        }
                    ],
                },
            )
            if response.status_code == 200:
                response_json = response.json()
                anscestors = set()
                for response_term in response_json["expansion"]["contains"]:
                    anscestors.add(
                        "SNOMED:" + response_term["code"]
                        if snomed
                        else response_term["code"]
                    )
                return (term, anscestors)
            else:
                time.sleep(1)

        if response.status_code != 200:
            print(f"Error fetching term from Ontoserver {term}")

    # END subroutines

    ontology_clusters = get_ontologies_clusters()
    executor = ThreadPoolExecutor(500)
    futures = []

    for ontology, terms in ontology_clusters.items():
        if ontology == "SNOMED":
            for term in terms:
                # fetch only anscestors that aren't fetched yet
                try:
                    data = Anscestors.get(term)
                except Anscestors.DoesNotExist:
                    futures.append(
                        executor.submit(threaded_request_ontoserver, term, ONTOSERVER)
                    )
        else:
            for term in terms:
                # fetch only anscestors that aren't fetched yet
                try:
                    data = Anscestors.get(term)
                except Anscestors.DoesNotExist:
                    # details will be missing if the ontology info is not in OLS
                    if details := get_ontology_details(ontology):
                        data = json.loads(details.data)
                        iri = data["baseUri"] + term.split(":")[1]
                        iri_double_encoded = urllib.parse.quote_plus(
                            urllib.parse.quote_plus(iri)
                        )
                        url = f"{ENSEMBL_OLS}/{ontology}/terms/{iri_double_encoded}/hierarchicalAncestors"
                        futures.append(
                            executor.submit(threaded_request_ensemble, term, url)
                        )
    term_anscestors = defaultdict(set)

    for future in as_completed(futures):
        term, ancestors = future.result()
        if ancestors:
            term_anscestors[term].update(ancestors)
            term_anscestors[term].add(term)

    term_descendants = defaultdict(set)

    with Anscestors.batch_write() as batch:
        for term, anscestors in term_anscestors.items():
            item = Anscestors(term)
            item.anscestors = anscestors
            batch.save(item)

            for anscestor in anscestors:
                term_descendants[anscestor].add(term)

    with Descendants.batch_write() as batch:
        for term, descendants in term_descendants.items():
            # if descendants are recorded, just update, else make record
            try:
                item = Descendants.get(term)
                item.update(actions=[Descendants.descendants.add(descendants)])
            except Descendants.DoesNotExist:
                item = Descendants(term)
                item.descendants = descendants
                batch.save(item)


def update_athena_partitions(table):
    athena.start_query_execution(
        QueryString=f"MSCK REPAIR TABLE `{table}`",
        # ClientRequestToken='string',
        QueryExecutionContext={"Database": ENV_ATHENA.ATHENA_METADATA_DATABASE},
        WorkGroup=ENV_ATHENA.ATHENA_WORKGROUP,
    )


def await_result(execution_id, sleep=2):
    retries = 0
    while True:
        exec = athena.get_query_execution(QueryExecutionId=execution_id)
        status = exec["QueryExecution"]["Status"]["State"]

        if status in ("QUEUED", "RUNNING"):
            print(f"Sleeping {sleep} seconds")
            time.sleep(sleep)
            retries += 1

            if retries == 60:
                print("Timed out")
                return []
            continue
        elif status in ("FAILED", "CANCELLED"):
            print("Error: ", exec["QueryExecution"]["Status"])
            raise Exception("Error: " + str(exec["QueryExecution"]["Status"]))
        elif status == "SUCCEEDED":
            return


def drop_tables(table):
    query = f"DROP TABLE IF EXISTS {table};"
    response = athena.start_query_execution(
        QueryString=query,
        QueryExecutionContext={"Database": ENV_ATHENA.ATHENA_METADATA_DATABASE},
        WorkGroup=ENV_ATHENA.ATHENA_WORKGROUP,
    )
    await_result(response["QueryExecutionId"])


def clean_files(bucket, prefix):
    has_more = True
    while has_more:
        response = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
        files_to_delete = []
        for object in response.get("Contents", []):
            files_to_delete.append({"Key": object["Key"]})
        if files_to_delete:
            s3.delete_objects(Bucket=bucket, Delete={"Objects": files_to_delete})
        has_more = response["IsTruncated"]
    time.sleep(1)


def ctas_basic_tables(
    *, source_table, destination_table, destination_prefix, bucket_count
):
    clean_files(ENV_ATHENA.ATHENA_METADATA_BUCKET, destination_prefix)
    drop_tables(destination_table)

    query = CTAS_TEMPLATE.format(
        target=destination_table,
        uri=f"s3://{ENV_ATHENA.ATHENA_METADATA_BUCKET}/{destination_prefix}",
        bucket_by="id",
        table=source_table,
        bucket_count=bucket_count,
    )
    response = athena.start_query_execution(
        QueryString=query,
        QueryExecutionContext={"Database": ENV_ATHENA.ATHENA_METADATA_DATABASE},
        WorkGroup=ENV_ATHENA.ATHENA_WORKGROUP,
    )
    await_result(response["QueryExecutionId"])


def index_terms():
    clean_files(ENV_ATHENA.ATHENA_METADATA_BUCKET, "terms-index/")
    drop_tables(ENV_ATHENA.ATHENA_TERMS_INDEX_TABLE)

    response = athena.start_query_execution(
        QueryString=INDEX_QUERY,
        QueryExecutionContext={"Database": ENV_ATHENA.ATHENA_METADATA_DATABASE},
        WorkGroup=ENV_ATHENA.ATHENA_WORKGROUP,
    )
    await_result(response["QueryExecutionId"])


def record_terms():
    clean_files(ENV_ATHENA.ATHENA_METADATA_BUCKET, "terms/")
    drop_tables(ENV_ATHENA.ATHENA_TERMS_TABLE)

    response = athena.start_query_execution(
        QueryString=TERMS_QUERY,
        QueryExecutionContext={"Database": ENV_ATHENA.ATHENA_METADATA_DATABASE},
        WorkGroup=ENV_ATHENA.ATHENA_WORKGROUP,
    )
    await_result(response["QueryExecutionId"])


def record_relations():
    clean_files(ENV_ATHENA.ATHENA_METADATA_BUCKET, "relations/")
    drop_tables(ENV_ATHENA.ATHENA_RELATIONS_TABLE)

    response = athena.start_query_execution(
        QueryString=RELATIONS_QUERY,
        QueryExecutionContext={"Database": ENV_ATHENA.ATHENA_METADATA_DATABASE},
        WorkGroup=ENV_ATHENA.ATHENA_WORKGROUP,
    )
    await_result(response["QueryExecutionId"])


# TODO re-evaluate the following function remove or useful?
def onto_index():
    response = athena.start_query_execution(
        QueryString=ONTO_TERMS_QUERY,
        QueryExecutionContext={"Database": ENV_ATHENA.ATHENA_METADATA_DATABASE},
        WorkGroup=ENV_ATHENA.ATHENA_WORKGROUP,
    )
    execution_id = response["QueryExecutionId"]
    await_result(execution_id)

    with sopen(
        f"s3://{ENV_ATHENA.ATHENA_METADATA_BUCKET}/query-results/{execution_id}.csv"
    ) as s3f:
        for n, line in enumerate(s3f):
            if n == 0:
                continue
            term, tablename, colname, type, label = [
                item.strip('"') for item in line.strip().split(",")
            ]
            entry = OntoData.make_index_entry(
                term=term,
                tableName=tablename,
                columnName=colname,
                type=type,
                label=label,
            )
            entry.save()
    return


def lambda_handler(event, context):
    # CTAS this must finish before all
    threads = []
    for src, dest, prefix, bucket_count in (
        (
            ENV_ATHENA.ATHENA_DATASETS_CACHE_TABLE,
            ENV_ATHENA.ATHENA_DATASETS_TABLE,
            "datasets/",
            10,
        ),
        (
            ENV_ATHENA.ATHENA_COHORTS_CACHE_TABLE,
            ENV_ATHENA.ATHENA_COHORTS_TABLE,
            "cohorts/",
            10,
        ),
        (
            ENV_ATHENA.ATHENA_INDIVIDUALS_CACHE_TABLE,
            ENV_ATHENA.ATHENA_INDIVIDUALS_TABLE,
            "individuals/",
            20,
        ),
        (
            ENV_ATHENA.ATHENA_BIOSAMPLES_CACHE_TABLE,
            ENV_ATHENA.ATHENA_BIOSAMPLES_TABLE,
            "biosamples/",
            20,
        ),
        (
            ENV_ATHENA.ATHENA_RUNS_CACHE_TABLE,
            ENV_ATHENA.ATHENA_RUNS_TABLE,
            "runs/",
            20,
        ),
        (
            ENV_ATHENA.ATHENA_ANALYSES_CACHE_TABLE,
            ENV_ATHENA.ATHENA_ANALYSES_TABLE,
            "analyses/",
            20,
        ),
    ):
        threads.append(
            threading.Thread(
                target=ctas_basic_tables,
                kwargs={
                    "source_table": src,
                    "destination_table": dest,
                    "destination_prefix": prefix,
                    "bucket_count": bucket_count,
                },
            )
        )
        threads[-1].start()
    [thread.join() for thread in threads]

    # this is the longest process
    index_thread = threading.Thread(target=index_terms)
    index_thread.start()

    relations_thread = threading.Thread(target=record_relations)
    relations_thread.start()

    # terms are neded for the tree index
    terms_thread = threading.Thread(target=record_terms)
    terms_thread.start()
    terms_thread.join()
    index_terms_tree()

    # join last running threads
    index_thread.join()
    relations_thread.join()
    print("Success")


if __name__ == "__main__":
    lambda_handler({}, {})
    pass
