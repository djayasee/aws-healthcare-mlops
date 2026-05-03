import json
import os
import boto3


def parse_edi_837(edi_text):
    claims = []
    segments = edi_text.strip().split("~")

    claim = {}
    for segment in segments:
        elements = segment.strip().split("*")
        tag = elements[0]

        if tag == "CLM":
            claim["claim_id"] = elements[1]
            claim["claim_amount"] = elements[2]

        elif tag == "NM1" and elements[1] == "IL":
            claim["patient_last_name"] = elements[3]
            claim["patient_first_name"] = elements[4]

        elif tag == "NM1" and elements[1] == "85":
            claim["provider_last_name"] = elements[3]
            claim["provider_first_name"] = elements[4]

        elif tag == "SV1":
            claim["service_code"] = elements[1].split(":")[1]
            claim["service_charge"] = elements[2]
            claim["service_units"] = elements[4]

        elif tag == "SE":
            if claim:
                claims.append(claim)
                claim = {}

    return claims


def lambda_handler(event, context):
    s3 = boto3.client("s3")
    sqs = boto3.client("sqs")

    queue_url = os.environ["SQS_QUEUE_URL"]

    for record in event["Records"]:
        bucket = record["s3"]["bucket"]["name"]
        key = record["s3"]["object"]["key"]

        response = s3.get_object(Bucket=bucket, Key=key)
        edi_text = response["Body"].read().decode("utf-8")

        claims = parse_edi_837(edi_text)

        for claim in claims:
            sqs.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps(claim),
            )

    return {"statusCode": 200, "body": f"Processed {len(claims)} claims"}
