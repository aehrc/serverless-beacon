#!/bin/bash
FUNCTION_NAME="queryDatasets"

zip -FS /tmp/lambda-$FUNCTION_NAME.zip lambda_function.py api_response.py chrom_matching.py lambda_utils.py tabix
