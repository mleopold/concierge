package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io/ioutil"
	"log"
	"net/http"
	"os"
	"time"
	"strings"
	"path/filepath"

	"github.com/aws/aws-lambda-go/lambda"
	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/aws/external"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/disintegration/imaging"
)

type teamsResponse struct {
	Type       string          `json:"@type"`
	Context    string          `json:"@context"`
	ThemeColor string          `json:"themeColor"`
	Summary    string          `json:"summary"`
	Title      string          `json:"title"`
	Text       string          `json:"text"`
	Sections   json.RawMessage `json:"sections"`
}

type IoT struct {
	Username  	string `json:"username"`
	Command     string `json:"command"`
	S3Key 		string `json:"s3key"`
}

const smallHeight = 400

func main() {
	log.SetFlags(log.LstdFlags | log.Lshortfile)
	lambda.Start(handler)
}

func handler(event IoT) error {
	bucketName := os.Getenv("BUCKET_NAME")
	teamsWebhookURL := os.Getenv("TEAMS_WEBHOOK")
	trainURL := os.Getenv("TRAIN_URL")

	log.Printf("sending welcome message to Teams")

	// thumbnail
	name := strings.TrimSuffix(event.S3Key, filepath.Ext(event.S3Key))
	keySmall := name + "_small.jpg"
	
	var message teamsResponse
	if strings.Compare(event.Command, "open") == 0 {
		message = getWelcomeMessage(event.Username, bucketName, keySmall)
	} else if (strings.Compare(event.Command, "unknown") == 0) {
		message = getUnownMessage(bucketName, keySmall, trainURL)
	} else {
		return fmt.Errorf("Unknown event %s", event.Command)
	}

	err := thumbnail(bucketName, event.S3Key, keySmall)
	if err != nil {
		log.Printf("error resizing %s", err)
		keySmall = event.S3Key
	}

	body, _ := json.Marshal(message)

	req, err := http.NewRequest("POST", teamsWebhookURL, bytes.NewBuffer(body))
	req.Header.Add("Content-Type", "application/json")
	client := &http.Client{
		Timeout: 5 * time.Second,
	}

	resp, err := client.Do(req)
	if err != nil {
		log.Printf("teams - error: %v", err)

		return fmt.Errorf("teams - error")
	}
	defer resp.Body.Close()

	b, _ := ioutil.ReadAll(resp.Body)
	if resp.StatusCode != http.StatusOK {
		log.Printf("teams - response code: %v", resp.StatusCode)
		log.Printf("teams - body: %s", b) // debug

		return fmt.Errorf("teams - unreachable")
	}

	return nil
}

func getWelcomeMessage(userName string, bucketName string, keySmall string) teamsResponse {
	msg := teamsResponse{
		Type:       "MessageCard",
		Context:    "http://schema.org/extensions",
		ThemeColor: "ccc",
		Title:      fmt.Sprintf("Welcome to the office %s", userName),
		Text:       fmt.Sprintf("![who](https://s3.amazonaws.com/%s/%s)", bucketName, keySmall),
	}
	return msg
}

func getUnownMessage(bucketName string, keySmall string, trainURL string) teamsResponse {
	msg := teamsResponse{
		Type:       "MessageCard",
		Context:    "http://schema.org/extensions",
		ThemeColor: "ccc",
		Summary:    "I don't know who this is...",
		Title:      "I don't know who this is...",
		Text:       fmt.Sprintf("![who](https://s3.amazonaws.com/%s/%s)", bucketName, keySmall),
		Sections: json.RawMessage(fmt.Sprintf(`[{
			"potentialAction": [{
				"@type": "ActionCard",
				"name": "who",
				"inputs": [{
					"@type": "TextInput",
					"id": "name",
					"placeholder": "name",
					"title": "whodisis"
				}],
				"actions": [{
					"@type": "HttpPOST",
					"name": "Submit",
					"target": "%s",
					"body": "{\"action\": \"train\", \"key\": \"%s\", \"name\": \"{{name.value}}\"}",
					"headers": [{
						"Content-Type": "application/json"
				    	}]
			    	},{
					"@type": "HttpPOST",
					"name": "Discard",
					"target": "%s",
					"body": "{\"action\": \"discard\", \"key\": \"%s\"}",
					"headers": [{
						"Content-Type": "application/json"
				    	}]
			    	}]	
			}]
		}]`, trainURL, keySmall, trainURL, keySmall)),
	}
	return msg
}

func thumbnail(bucketName, originalKey string, outputKey string) error {
	cfg, err := external.LoadDefaultAWSConfig()
	if err != nil {
		return err
	}
	client := s3.New(cfg)

	log.Printf("s3 GET object %s/%s", bucketName, originalKey)
	result, err := client.GetObjectRequest(&s3.GetObjectInput{
		Bucket: aws.String(bucketName),
		Key:    aws.String(originalKey),
	}).Send()
	if err != nil {
		log.Printf("%s", err)
		return err
	}

	log.Printf("decoding image")
	srcimg, err := imaging.Decode(result.Body)
	if err != nil {
		log.Printf("%s", err)
		return err
	}

	log.Printf("resizing image")
	dstimg := imaging.Resize(srcimg, 0, smallHeight, imaging.Linear)

	buf := new(bytes.Buffer)
	// err = imaging.Encode(buf, dstimg, imaging.JPEG)
	imaging.Encode(buf, dstimg, imaging.JPEG, imaging.JPEGQuality(90))
	if err != nil {
		log.Printf("%s", err)
		return err
	}

	log.Printf("Image %s resized to %s", bucketName, originalKey, outputKey)
	_, err = client.PutObjectRequest(&s3.PutObjectInput{
		Bucket:      aws.String(bucketName),
		Key:         aws.String(outputKey),
		Body:        bytes.NewReader(buf.Bytes()),
		ACL:         s3.ObjectCannedACLPublicRead,
		ContentType: aws.String("image/jpeg"),
	}).Send()
	if err != nil {
		log.Printf("%s", err)
		return err
	}

	return nil
}
