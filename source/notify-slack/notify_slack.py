# Adapted from https://github.com/svdgraaf/doorman

import boto3
from botocore.vendored import requests
import time
from decimal import *
import os
import json

slack_token = os.environ['SLACK_API_TOKEN']
slack_channel_id = os.environ['SLACK_CHANNEL_ID']
webhook_url = os.environ['SLACK_API_URL']
print_debug = True if 'DEBUG' in os.environ else False
bucket_name = os.environ["BUCKET_NAME"]

def function_handler(event, context):

    if 'username' not in event:
        msg = "no username field in payload"
        print(msg)
        return {
        'statusCode': 500,
        'body': json.dumps(msg)
        }

    if 'command' not in event:
        msg = "Command was missing or not open"
        print (msg)
        return {
        'statusCode': 500,
        'body': json.dumps(msg)
        }

    if event['command'] == 'open':
        sendGreetingMessage(slack_token, event['username'], webhook_url, slack_channel_id, event['s3key'])
    elif event['command'] == 'unknown':
        sendUnknownMessage(slack_channel_id, event['s3key'], slack_token)

    return

def sendGreetingMessage(slackToken, userId, webhookUrl, slackChannelId, S3Key):
    # Fetch 'username' corresponding to the 'user_id' from event
    data = {
        "token": slackToken,
        "user": user_id
    }
    if print_debug is True:  print(data)
    resp = requests.post("%susers.info" % webhookUrl, data=data)
    if print_debug is True: print(resp.content)
    if print_debug is True: print(resp.json())

    username = resp.json()['user']['name']

    data = {
        "channel": slackChannelId,
        "text": "Welcome @%s" % username,
        "link_names": True,
        "attachments": [
            {
                "image_url": "https://s3.amazonaws.com/%s/%s" % (bucket_name, S3key),
                "fallback": "Nope?",
                "attachment_type": "default",
            }
        ]
    }
    resp = requests.post("%schat.postMessage" % webhook_url,
           headers={'Content-Type':'application/json;charset=UTF-8',
           'Authorization': 'Bearer %s' % slack_token}, json=data)


def sendUnknownMessage(slackChannelId, S3Key, slackToken):
    data = {
        "channel": slackChannelId,
        "text": "I don't know who this is, can you tell me?",
        "attachments": [
            {
                "image_url": "https://s3.amazonaws.com/%s/%s" % (bucket_name, S3Key),
                "fallback": "Nope?",
                "callback_id": S3Key,
                "attachment_type": "default",
                "actions": [{
                        "name": "username",
                        "text": "Select a username...",
                        "type": "select",
                        "data_source": "users"
                    },
                    {
                        "name": "discard",
                        "text": "Ignore",
                        "style": "danger",
                        "type": "button",
                        "value": "ignore",
                        "confirm": {
                            "title": "Are you sure?",
                            "text": "Are you sure you want to ignore and delete this image?",
                            "ok_text": "Yes",
                            "dismiss_text": "No"
                        }
                    }
                ]
            }
        ]
    }
    print(data)
    foo = requests.post("https://slack.com/api/chat.postMessage", headers={'Content-Type':'application/json;charset=UTF-8', 'Authorization': 'Bearer %s' % slackToken}, json=data)
