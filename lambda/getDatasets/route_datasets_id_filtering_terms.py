import json
import csv

from smart_open import open as sopen

from shared.athena import run_custom_query
from shared.utils import ENV_ATHENA
from shared.apiutils import (
    RequestParams,
    build_filtering_terms_response,
    bundle_response,
)


def route(request: RequestParams, dataset_id):
    query = f"""
        SELECT DISTINCT term, label, type 
        FROM "{ENV_ATHENA.ATHENA_TERMS_TABLE}"
        WHERE term IN
        (
            SELECT DISTINCT TI.term
            FROM "{ENV_ATHENA.ATHENA_TERMS_INDEX_TABLE}" TI
            WHERE TI.id = '{dataset_id}' and TI.kind = 'datasets'

            UNION

            SELECT DISTINCT TI.term
            FROM "{ENV_ATHENA.ATHENA_INDIVIDUALS_TABLE}" I
            JOIN 
            "{ENV_ATHENA.ATHENA_TERMS_INDEX_TABLE}" TI
            ON TI.id = I.id and TI.kind = 'individuals'
            WHERE I._datasetid = '{dataset_id}'

            UNION

            SELECT DISTINCT TI.term
            FROM "{ENV_ATHENA.ATHENA_BIOSAMPLES_TABLE}" B
            JOIN 
            "{ENV_ATHENA.ATHENA_TERMS_INDEX_TABLE}" TI
            ON TI.id = B.id and TI.kind = 'biosamples'
            WHERE B._datasetid = '{dataset_id}'

            UNION

            SELECT DISTINCT TI.term
            FROM "{ENV_ATHENA.ATHENA_RUNS_TABLE}" R
            JOIN 
            "{ENV_ATHENA.ATHENA_TERMS_INDEX_TABLE}" TI
            ON TI.id = R.id and TI.kind = 'runs'
            WHERE R._datasetid = '{dataset_id}'

            UNION

            SELECT DISTINCT TI.term
            FROM "{ENV_ATHENA.ATHENA_ANALYSES_TABLE}" A
            JOIN 
            "{ENV_ATHENA.ATHENA_TERMS_INDEX_TABLE}" TI
            ON TI.id = A.id and TI.kind = 'analyses'
            WHERE A._datasetid = '{dataset_id}'
        )
        ORDER BY term
        OFFSET {request.query.pagination.skip}
        LIMIT {request.query.pagination.limit};
    """

    print("Performing query \n", query)

    exec_id = run_custom_query(query, return_id=True)
    filteringTerms = []

    with sopen(
        f"s3://{ENV_ATHENA.ATHENA_METADATA_BUCKET}/query-results/{exec_id}.csv"
    ) as s3f:
        reader = csv.reader(s3f)

        for n, row in enumerate(reader):
            if n == 0:
                continue
            term, label, typ = row
            filteringTerms.append({"id": term, "label": label, "type": typ})

    response = build_filtering_terms_response(filteringTerms, [], request)

    print("Returning Response: {}".format(json.dumps(response)))
    return bundle_response(200, response)
