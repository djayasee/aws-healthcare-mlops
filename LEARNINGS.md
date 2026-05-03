# EDI Claims Anomaly Detection — Step-by-Step Build Log

## Project Goal
Build an end-to-end AWS pipeline that ingests EDI 837 healthcare claims files,
parses them, and detects anomalies using ML.

---

## Step 1 — Project Skeleton
Already completed before this session. Folder structure:
```
aws-healthcare-mlops/
  app.py              → CDK entry point
  cdk.json            → CDK configuration
  infra/
    stack.py          → CDK infrastructure stack
    requirements.txt  → Python dependencies
  src/
    lambda/           → Lambda function code (future steps)
    ml/               → ML model code (future steps)
  notebooks/          → Jupyter notebooks (future steps)
```

---

## Step 2 — Write the CDK Stack

### What is CDK?
AWS CDK (Cloud Development Kit) lets you define AWS infrastructure as Python code.
CDK translates your Python into a CloudFormation template and deploys it to AWS.

### Install Python dependencies
```bash
pip install -r infra/requirements.txt
```
Installs `aws-cdk-lib` and `constructs` — the Python packages for CDK.

### Install CDK CLI
```bash
npm install -g aws-cdk
cdk --version
```
The CDK CLI is a Node.js tool separate from the Python library.
Used to run `cdk synth` and `cdk deploy`.

### Create the stack file
```bash
touch infra/stack.py
```

### What we built in `infra/stack.py`

#### Imports
```python
import aws_cdk as cdk
from aws_cdk import (
    aws_s3 as s3,
    aws_sqs as sqs,
    aws_kms as kms,
    aws_iam as iam,
    Duration,
    RemovalPolicy,
)
from constructs import Construct
```
- `constructs` is the foundational library CDK is built on. Every resource (bucket, queue, role) is a "Construct" — a node in a parent→child tree.
- `Duration` is a helper for expressing time (e.g. `Duration.days(14)`).
- `RemovalPolicy` controls what happens to a resource when the stack is deleted.

#### Stack Class
```python
class EdiAnomalyStack(cdk.Stack):
    def __init__(self, scope: Construct, id: str, **kwargs):
        super().__init__(scope, id, **kwargs)
```
Every CDK stack is a Python class inheriting from `cdk.Stack`.
`super().__init__()` is always required — it initializes CDK internals.

#### KMS Key (created first — everything else references it)
```python
self.encryption_key = kms.Key(
    self, "EdiEncryptionKey",
    enable_key_rotation=True,
    removal_policy=RemovalPolicy.RETAIN,
)
```
- Customer-managed KMS key encrypts all S3 and SQS data at rest.
- `enable_key_rotation=True` — AWS rotates the key yearly (HIPAA requirement).
- `removal_policy=RETAIN` — never delete the key on stack teardown (data would become unreadable).

#### Two S3 Buckets
```python
self.raw_bucket = s3.Bucket(self, "RawEdiBucket",
    bucket_name=f"edi-raw-{self.account}-{self.region}",
    block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
    versioned=True,
    encryption=s3.BucketEncryption.KMS,
    encryption_key=self.encryption_key,
    removal_policy=RemovalPolicy.RETAIN,
)
```
- **Why two buckets?** Raw = untouched source of truth. Processed = parsed output.
  If parser logic changes, you can reprocess from raw.
- `block_public_access=BLOCK_ALL` — bucket can never be made public (required for PHI/HIPAA).
- `versioned=True` — keeps old file versions for audit trail.
- Bucket names include account ID + region to guarantee global uniqueness.
- Bucket names use hyphens only — S3 does not allow underscores.

#### SQS Dead Letter Queue (DLQ) — created before main queue
```python
self.dlq = sqs.Queue(self, "EdiDlq",
    queue_name="edi-anomaly-dlq",
    encryption=sqs.QueueEncryption.KMS,
    encryption_master_key=self.encryption_key,
    retention_period=Duration.days(14),
)
```
- If Lambda fails to process a message after retries, it lands here instead of being lost.
- `retention_period=Duration.days(14)` — keep failed messages 2 weeks for inspection/reprocessing.

#### SQS Main Queue
```python
self.queue = sqs.Queue(self, "EdiQueue",
    queue_name="edi-anomaly-queue",
    encryption=sqs.QueueEncryption.KMS,
    encryption_master_key=self.encryption_key,
    visibility_timeout=Duration.seconds(300),
    dead_letter_queue=sqs.DeadLetterQueue(
        max_receive_count=3,
        queue=self.dlq,
    ),
)
```
- **Why SQS between S3 and Lambda?** Adds buffering, retry logic, and backpressure.
- `visibility_timeout` — how long Lambda has to process one message before SQS retries it.
  Must equal or exceed your Lambda timeout.
- `max_receive_count=3` — retry 3 times before sending to DLQ.

#### IAM Roles (Least Privilege)
```python
self.parser_lambda_role = iam.Role(self, "EdiParserLambdaRole",
    assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
    managed_policies=[AWSLambdaBasicExecutionRole],
)
self.raw_bucket.grant_read(self.parser_lambda_role)
self.processed_bucket.grant_write(self.parser_lambda_role)
self.encryption_key.grant_encrypt_decrypt(self.parser_lambda_role)
self.queue.grant_consume_messages(self.parser_lambda_role)
```
- Each Lambda gets only the permissions it needs — nothing more.
- `grant_read()`, `grant_write()` — CDK helper methods that add exact S3 permissions automatically.
- **Parser Lambda**: read raw → write processed → consume SQS messages.
- **Anomaly Lambda**: read processed only. Cannot touch raw data or SQS.

#### CloudFormation Outputs
```python
cdk.CfnOutput(self, "RawBucketName", value=self.raw_bucket.bucket_name)
```
After deploy, these values are printed to the terminal and stored in CloudFormation.
Other stacks and scripts can reference them without hardcoding ARNs.

### Create `app.py` (CDK entry point)
```python
import aws_cdk as cdk
from infra.stack import EdiAnomalyStack

app = cdk.App()
EdiAnomalyStack(app, "EdiAnomalyStack")
app.synth()
```
CDK needs a top-level app object to discover your stacks.
`cdk.json` points to this file: `{ "app": "python app.py" }`.

### Verify syntax
```bash
python -m py_compile infra/stack.py && echo "OK"
```
Checks for syntax errors without running the file.

### Preview the CloudFormation template
```bash
cdk synth
```
Converts Python CDK code to CloudFormation YAML/JSON and prints it.
Nothing is deployed — it is a preview only.
Output saved to `cdk.out/EdiAnomalyStack.template.json`.

---

## Step 3 — Deploy the Stack

### AWS credentials
```bash
aws sts get-caller-identity
```
Confirms which AWS account and user your terminal is authenticated as.
Credentials are configured via `aws configure` (Access Key ID + Secret Access Key).

### Bootstrap (one-time per account/region)
```bash
cdk bootstrap
```
Sets up CDK's own prerequisites in your AWS account:
- An S3 bucket for CDK deployment assets
- IAM roles CDK uses to deploy on your behalf

**Analogy:** Bootstrap = setting up the construction site. Deploy = building the house.
Only needs to be run once per account/region.

### Deploy
```bash
cdk deploy
```
Creates all your real AWS resources. CDK shows IAM changes and asks for confirmation.
Type `y` to proceed.

### Resources created (account: 015932244777, region: us-east-1)
| Resource | Name/ARN |
|---|---|
| KMS Key | `arn:aws:kms:us-east-1:015932244777:key/a5839094-9ffe-442e-8527-d935264658e6` |
| S3 Raw Bucket | `edi-raw-015932244777-us-east-1` |
| S3 Processed Bucket | `edi-processed-015932244777-us-east-1` |
| SQS Queue | `edi-anomaly-queue` |
| SQS DLQ | `edi-anomaly-dlq` |
| IAM Role | `EdiParserLambdaRole` |
| IAM Role | `AnomalyDetectorLambdaRole` |

### CloudFormation outputs after deploy
```
EdiAnomalyStack.DlqUrl = https://sqs.us-east-1.amazonaws.com/015932244777/edi-anomaly-dlq
EdiAnomalyStack.KmsKeyArn = arn:aws:kms:us-east-1:015932244777:key/a5839094-...
EdiAnomalyStack.ProcessedBucketName = edi-processed-015932244777-us-east-1
EdiAnomalyStack.QueueUrl = https://sqs.us-east-1.amazonaws.com/015932244777/edi-anomaly-queue
EdiAnomalyStack.RawBucketName = edi-raw-015932244777-us-east-1
```

---

## Python Lessons Learned

### Indentation rule
```
class (0 spaces)
    def __init__ (4 spaces)
        statements (8 spaces)
            args inside () (12 spaces)
```
Python uses indentation instead of braces. Every level = 4 spaces.

### One statement per line
Python requires each statement on its own line.
Two statements on the same line causes `SyntaxError: invalid syntax`.

### Variable names must be consistent
If you define `self.raw_bucket`, you must use `self.raw_bucket` everywhere.
`self.raw_buck` and `self.raw_bucket` are different variables.

### Class names are case-sensitive
`cdk.Stack` exists. `cdk.stack` does not. Python is case-sensitive.

### Import aliases must match usage
If you write `import aws_cdk as cdk`, you must use `cdk.Stack` not `aws_cdk.Stack`.

---

---

## Step 4 — Write the Lambda Function (`src/lambda/edi_parser.py`)

### What this Lambda does
Triggered when an EDI file lands in the raw S3 bucket.
Reads the file, parses it into individual claims, sends each claim as a JSON message to SQS.

### Create the file
```bash
touch src/lambda/edi_parser.py
```

### Block 1 — Imports
```python
import json
import os
import boto3
```

| Import | Why |
|---|---|
| `json` | Converts parsed EDI data (Python dict) into a JSON string for SQS |
| `os` | Reads environment variables — never hardcode bucket names or queue URLs |
| `boto3` | AWS SDK for Python — how Lambda talks to S3 and SQS |

### Block 2 — EDI Parser Function

#### What is X12 837?
X12 837 is the standard file format for healthcare claims in the US (HIPAA-mandated).
A raw EDI file looks like:
```
ISA*00*...*ZZ*SENDER*ZZ*RECEIVER~
CLM*CLAIM001*500.00***11:B:1~
NM1*IL*1*SMITH*JOHN~
NM1*85*2*GENERAL HOSPITAL~
SV1*HC:99213*150.00*UN*1~
SE*10*0001~
```

| Symbol | Meaning |
|---|---|
| `~` | Segment terminator — marks end of each segment (like a line ending) |
| `*` | Element separator — separates fields within a segment (like a comma in CSV) |
| `CLM` | Claim segment — contains claim ID and total amount |
| `NM1*IL` | Patient name (`IL` = Insured/Patient) |
| `NM1*85` | Provider name (`85` = Billing Provider) |
| `SV1` | Service line — procedure code, charge, units |
| `SE` | End of transaction — signals one complete claim |

**Why split on `~` first, then `*`?**
EDI files are not line-by-line. `~` marks segment ends. Inside each segment, `*` separates fields.
Always parse in two steps: segments first, elements second.

```python
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
```

### Block 3 — Lambda Handler
```python
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
```

| Line | Why |
|---|---|
| `boto3.client("s3")` | Creates an S3 client — connection to S3 |
| `boto3.client("sqs")` | Creates an SQS client — connection to SQS |
| `os.environ["SQS_QUEUE_URL"]` | Reads queue URL from environment variable — never hardcode |
| `event["Records"]` | Lambda receives a list of S3 events — one per uploaded file |
| `record["s3"]["bucket"]["name"]` | Which bucket the file landed in |
| `record["s3"]["object"]["key"]` | Filename/path of the uploaded EDI file |
| `s3.get_object(...)` | Downloads the EDI file content from S3 |
| `.read().decode("utf-8")` | Converts file bytes into a Python string |
| `json.dumps(claim)` | Converts Python dict to JSON string — SQS only accepts strings |

**Why does Lambda receive `event["Records"]` as a list?**
If multiple EDI files land in S3 at the same time, AWS batches them into one Lambda invocation.
Looping through `Records` ensures none are missed.

---

---

## Step 5 — Create 10 Synthetic Test Claims (`src/lambda/generate_test_claims.py`)

### What this script does
Generates 10 fake but realistic EDI 837 claim files for testing.
No real patient data — everything is made up but follows correct healthcare formats.

### Reference data used

| Variable | What it represents |
|---|---|
| `PROVIDERS` | Fake doctors with 10-digit NPI numbers (HIPAA standard) |
| `PATIENTS` | Fake patients with `age_group` instead of exact DOB — avoids PHI |
| `CPT_CODES` | Current Procedural Terminology — standard US medical procedure codes |
| `DIAGNOSIS_CODES` | ICD-10 codes — standard diagnosis codes (e.g. `I10` = hypertension) |
| `typical_charge` | Realistic dollar amounts per procedure |

**Why `age_group` instead of exact age?**
Bucketing ages (`31-45`) reduces sensitivity while still being useful for anomaly detection.

### How anomalies are injected
```python
anomaly = i in [3, 7]          # claims 3 and 7 are anomalies
charge = charge * random.uniform(5, 10)  # anomaly = 5-10x normal charge
```
Claims 3 and 7 are hardcoded as anomalies so we can verify the ML model finds them later.
This is called **labeled data** — you know the ground truth to measure model accuracy.

### Output
- `test_data/claim_001.edi` through `claim_010.edi` — EDI 837 formatted files
- `test_data/manifest.json` — summary of all 10 claims with fields and anomaly flag

### Actual results
| Claim | CPT | Charge | Anomaly |
|---|---|---|---|
| 1 | 99213 Office visit | $450 | No |
| 2 | 80053 Metabolic panel | $285 | No |
| 3 | 99285 Emergency dept | **$21,354** | **Yes** |
| 4 | 70553 MRI brain | $6,600 | No |
| 5 | 71046 Chest X-ray | $360 | No |
| 6 | 99213 Office visit | $150 | No |
| 7 | 99214 Office visit | **$1,137** | **Yes** |
| 8 | 99213 Office visit | $450 | No |
| 9 | 99285 Emergency dept | $2,550 | No |
| 10 | 93000 Electrocardiogram | $225 | No |

Claims 3 and 7 are 5–10x higher than normal — the pattern the ML model will learn to detect.

### Key Python concepts used

**`os.makedirs(output_dir, exist_ok=True)`**
Creates a folder if it doesn't exist. `exist_ok=True` means no error if it already exists.

**`f"{i:03d}"`**
Zero-padded number formatting. `i=1` becomes `001`, `i=10` becomes `010`.
Makes filenames sort correctly in directory listings.

**`if __name__ == "__main__"`**
Only runs the script when executed directly (`python script.py`).
Does NOT run when the file is imported by another script.
Standard Python pattern for any script that can also be used as a module.

---

*Steps 6+ coming soon...*
