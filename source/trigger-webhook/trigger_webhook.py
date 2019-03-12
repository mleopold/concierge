import boto3
from botocore.vendored import requests
import json
import os
import time
from decimal import *

webhook_url = os.environ['WEBHOOK_URL']
post_data = json.dumps(os.environ['WEBHOOK_POST_DATA']) if 'WEBHOOK_POST_DATA' in os.environ else {}

def function_handler(event, context):
    if 'username' not in event:
        msg = "no username field in payload"
        print(msg)
        return {
        'statusCode': 500,
        'body': json.dumps(msg)
        }

    if 'command' not in event or event['command'] != 'open':
        msg = "Command was missing or not open"
        print (msg)
        return {
        'statusCode': 500,
        'body': json.dumps(msg)
        }

    response = requests.post(
        webhook_url, data=json.dumps(post_data),
        headers={'Content-Type': 'application/json'}
    )

    if response.status_code != 200:
        msg = 'Request to webhook error %s, the response is:\n%s' % (response.status_code, response.text)
        return {
                'statusCode': 500,
                'body': json.dumps(msg)
        }

    return {
        'statusCode': 200,
        'body': json.dumps('Hello from Lambda!')
    }
