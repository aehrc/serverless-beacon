import boto3
from pynamodb.models import Model
from pynamodb.indexes import GlobalSecondaryIndex, AllProjection
from pynamodb.attributes import UnicodeAttribute

from shared.utils import ENV_DYNAMO


SESSION = boto3.session.Session()
REGION = SESSION.region_name


# Terms index
class TermIndex(GlobalSecondaryIndex):
    class Meta:
        index_name = "term_index"
        projection = AllProjection()
        billing_mode = "PAY_PER_REQUEST"
        region = REGION

    term = UnicodeAttribute(hash_key=True)


# TableNames
class TableIndex(GlobalSecondaryIndex):
    class Meta:
        index_name = "table_index"
        projection = AllProjection()
        billing_mode = "PAY_PER_REQUEST"
        region = REGION

    tableName = UnicodeAttribute(hash_key=True)


# TableNames
class TableTermsIndex(GlobalSecondaryIndex):
    class Meta:
        index_name = "tableterms_index"
        projection = AllProjection()
        billing_mode = "PAY_PER_REQUEST"
        region = REGION

    tableTerms = UnicodeAttribute(hash_key=True)


# ontoIndex table
class OntoData(Model):
    class Meta:
        table_name = ENV_DYNAMO.DYNAMO_ONTO_INDEX_TABLE
        region = REGION

    id = UnicodeAttribute(hash_key=True)
    tableTerms = UnicodeAttribute()
    tableName = UnicodeAttribute()
    columnName = UnicodeAttribute()
    term = UnicodeAttribute()
    label = UnicodeAttribute()
    type = UnicodeAttribute()

    termIndex = TermIndex()
    tableIndex = TableIndex()
    tableTermsIndex = TableTermsIndex()

    @classmethod
    def make_index_entry(cls, tableName, columnName, term, label, type):
        id = f"{tableName}\t{columnName}\t{term}"
        tableTerms = f"{tableName}\t{term}"
        entry = OntoData(hash_key=id)
        entry.tableName = tableName
        entry.tableTerms = tableTerms
        entry.columnName = columnName
        entry.term = term
        entry.label = label
        entry.type = type

        return entry


if __name__ == "__main__":
    pass
