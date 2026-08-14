#!/usr/bin/env bash
# Idempotent AWS infrastructure setup for the trading system.
# Run from a machine with AWS CLI configured (region us-east-1).
set -euo pipefail

REGION="us-east-1"
KEY_NAME="trading-system"
SG_NAME="trading-system-sg"
INSTANCE_TAG="trading-system"
DYNAMO_TABLE="trading-data"
S3_BUCKET="trading-datalake-920641308584"

# VPC — uses the account's default VPC
VPC_ID=$(aws ec2 describe-vpcs --filters "Name=isDefault,Values=true" --query 'Vpcs[0].VpcId' --output text --region "$REGION")
echo "VPC: $VPC_ID"

# 1. Key pair (store .pem OUTSIDE the git repo, e.g. ~/.ssh/)
if ! aws ec2 describe-key-pairs --key-name "$KEY_NAME" --region "$REGION" >/dev/null 2>&1; then
  aws ec2 create-key-pair --key-name "$KEY_NAME" --query 'KeyMaterial' --output text --region "$REGION" > ~/.ssh/${KEY_NAME}.pem
  chmod 400 ~/.ssh/${KEY_NAME}.pem
  echo "Key pair created -> ~/.ssh/${KEY_NAME}.pem"
else
  echo "Key pair exists"
fi

# 2. Security group (SSH only; dashboard via Cloudflare Tunnel later)
if ! aws ec2 describe-security-groups --group-names "$SG_NAME" --region "$REGION" >/dev/null 2>&1; then
  SG_ID=$(aws ec2 create-security-group --group-name "$SG_NAME" --description "Trading system VPS" --vpc-id "$VPC_ID" --query 'GroupId' --output text --region "$REGION")
  MY_IP=$(curl -s https://checkip.amazonaws.com)
  aws ec2 authorize-security-group-ingress --group-id "$SG_ID" --protocol tcp --port 22 --cidr "${MY_IP}/32" --region "$REGION"
  echo "SG created: $SG_ID (SSH from $MY_IP)"
else
  SG_ID=$(aws ec2 describe-security-groups --group-names "$SG_NAME" --query 'SecurityGroups[0].GroupId' --output text --region "$REGION")
  echo "SG exists: $SG_ID"
fi

# 3. Ubuntu 24.04 AMI
AMI_ID=$(aws ssm get-parameters --names /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id --query 'Parameters[0].Value' --output text --region "$REGION")
echo "AMI: $AMI_ID"

# 4. EC2 instance (t3.small, 30GB gp3)
INSTANCE_ID=$(aws ec2 run-instances \
  --image-id "$AMI_ID" --instance-type t3.small --key-name "$KEY_NAME" \
  --security-group-ids "$SG_ID" \
  --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":30,"VolumeType":"gp3"}}]' \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$INSTANCE_TAG}]" \
  --query 'Instances[0].InstanceId' --output text --region "$REGION")
echo "Instance: $INSTANCE_ID"

# 5. Elastic IP (stable address)
ALLOC_ID=$(aws ec2 allocate-address --domain vpc --query 'AllocationId' --output text --region "$REGION")
aws ec2 associate-address --instance-id "$INSTANCE_ID" --allocation-id "$ALLOC_ID" --region "$REGION"
EIP=$(aws ec2 describe-addresses --allocation-ids "$ALLOC_ID" --query 'Addresses[0].PublicIp' --output text --region "$REGION")
echo "Elastic IP: $EIP"

# 6. DynamoDB (single-table design)
aws dynamodb create-table --table-name "$DYNAMO_TABLE" \
  --attribute-definitions AttributeName=pk,AttributeType=S AttributeName=sk,AttributeType=S \
  --key-schema AttributeName=pk,KeyType=HASH AttributeName=sk,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST --region "$REGION" >/dev/null 2>&1 \
  && echo "DynamoDB created: $DYNAMO_TABLE" || echo "DynamoDB exists"

# 7. S3 bucket + versioning
aws s3api create-bucket --bucket "$S3_BUCKET" --region "$REGION" >/dev/null 2>&1 \
  && echo "S3 created: $S3_BUCKET" || echo "S3 exists"
aws s3api put-bucket-versioning --bucket "$S3_BUCKET" --versioning-configuration Status=Enabled --region "$REGION"

echo ""
echo "=== DONE ==="
echo "Instance: $INSTANCE_ID | IP: $EIP | Table: $DYNAMO_TABLE | Bucket: $S3_BUCKET"
