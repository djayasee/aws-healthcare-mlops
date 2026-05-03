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

*Steps 4+ coming soon...*
