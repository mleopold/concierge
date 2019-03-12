import boto3
from boto3.dynamodb.conditions import Key, Attr
import time
from decimal import *
import os
import json

iot_topic = os.environ['IOT_TOPPIC']

open_rate = int(os.environ['OPEN_RATE'])
unkown_rate = int(os.environ['UNKOWN_RATE'])

dynamodb = boto3.resource('dynamodb')
dynamodb_table = dynamodb.Table(os.environ['DYNAMODB_TABLE'])
iot_client = boto3.client('iot-data', region_name='us-east-1')

def lambda_handler(event, context):
    out_event = None

    if event['command'] == 'open' and checkNext(open_rate, "open", event['username']):
        out_event = event

    if event['command'] == 'unknown' and checkNext(unkown_rate, 'unkown', 'last'):
        out_event = event

    if out_event is not None:
        print("Publishing %s event" % str(out_event['command']))
        response = iot_client.publish(
            topic=iot_topic,
            qos=1,
            payload=json.dumps(out_event)
        )
    else:
        print ("No %s event not published, limited by rate" % str(event['command']))

def checkNext(grace, name, selector):
    now = time.time()
    cutoff = now-grace

    #print("Check next %s %s" % (name, selector))
    try:
        response = dynamodb_table.put_item(
            Item={'name': name, 'selector': selector, 'timestamp': str(now)},
            ConditionExpression = Attr('name').not_exists() | Attr('timestamp').lt(str(cutoff))
        )
        #print ("Dynamodb returned %s" % str(response))
    except Exception as e:
        print("Condition check threw exception %s with %s" % (str(type(e)), str(e)))
        return False

    return True
