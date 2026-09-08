#!/usr/bin/env python3
"""Launch a self-terminating spot-GPU instance to run the foundation-model benchmark."""
import boto3, base64, json, time

ec2 = boto3.client('ec2', region_name='us-east-1')
s3 = boto3.client('s3', region_name='us-east-1')
B = 'trading-datalake-920641308584'

# 1. ensure benchmark script is in S3 for the bootstrap to fetch
s3.upload_file('/home/ubuntu/trading-system/research/foundation_benchmark.py', B, 'research/foundation_benchmark.py')

# 2. self-terminating bootstrap: install chronos/timesfm, fetch+run script, persist to S3, shutdown
bootstrap = """#!/bin/bash
exec > /var/log/fb.log 2>&1
set -x
yum install -y python3-pip awscli >/dev/null 2>&1
pip3 install --no-cache-dir -q pandas boto3 numpy 2>&1 | tail -2
pip3 install --no-cache-dir -q torch --index-url https://download.pytorch.org/whl/cpu 2>&1 | tail -2
pip3 install --no-cache-dir -q chronos-forecasting timesfm 2>&1 | tail -3
aws s3 cp s3://TDBUCKET/research/foundation_benchmark.py /tmp/fb.py
python3 /tmp/fb.py
aws s3 cp /tmp/fb_result.json s3://TDBUCKET/research/foundation_benchmark_result.json
shutdown -h now
""".replace('TDBUCKET', B)

# 3. find a recent Amazon Linux 2 AMI
amis = ec2.describe_images(Filters=[{'Name':'name','Values':['amzn2-ami-hvm-*-x86_64-gp2']},
    {'Name':'state','Values':['available']}], Owners=['amazon'])
ami_id = sorted(amis['Images'], key=lambda i: i['CreationDate'])[-1]['ImageId']

# 4. launch ON-DEMAND instance (spot quota=0 on this account), self-terminating
r = ec2.run_instances(
    ImageId=ami_id,
    InstanceType='c5.2xlarge',
    MinCount=1,
    MaxCount=1,
    IamInstanceProfile={'Name': 'trading-vps-profile'},
    UserData=base64.b64encode(bootstrap.encode()).decode(),
    BlockDeviceMappings=[{'DeviceName':'/dev/xvda','Ebs':{'VolumeSize':40,'DeleteOnTermination':True}}],
)
inst_id = r['Instances'][0]['InstanceId']
print(f"INSTANCE: {inst_id}")
print(f"AMI: {ami_id}")
print("bootstrap: install torch(cpu)+chronos+timesfm -> fetch script -> run -> S3 -> shutdown")
