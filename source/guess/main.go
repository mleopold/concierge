package main

import (
	"crypto/md5"
	"encoding/json"
	"fmt"
	"log"
	"os"

	"github.com/aws/aws-lambda-go/events"
	"github.com/aws/aws-lambda-go/lambda"
	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/aws/external"
	"github.com/aws/aws-sdk-go-v2/service/iot"
	"github.com/aws/aws-sdk-go-v2/service/iotdataplane"
	"github.com/aws/aws-sdk-go-v2/service/rekognition"
	"github.com/aws/aws-sdk-go-v2/service/s3"
)

const smallHeight = 400

func main() {
	log.SetFlags(log.LstdFlags | log.Lshortfile)
	lambda.Start(handler)
}

func handler(event events.S3Event) error {
	key := event.Records[0].S3.Object.Key
	bucketName := os.Getenv("BUCKET_NAME")
	iotTopic := os.Getenv("IOT_TOPIC")

	cfg, err := external.LoadDefaultAWSConfig()

	// SearchFacesByImageRequest to rekognition
	rekClient := rekognition.New(cfg)
	rekResp, err := rekClient.SearchFacesByImageRequest(&rekognition.SearchFacesByImageInput{
		CollectionId: aws.String(os.Getenv("REKOGNITION_COLLECTION_ID")),
		Image: &rekognition.Image{
			S3Object: &rekognition.S3Object{
				Bucket: aws.String(bucketName),
				Name:   aws.String(key),
			},
		},
		MaxFaces:           aws.Int64(1),
		FaceMatchThreshold: aws.Float64(70),
	}).Send()
	if err != nil {
		return err
	}

	s3Client := s3.New(cfg)
	var userID, command, newKey string
	if len(rekResp.FaceMatches) == 0 {
		log.Printf("no matches found, sending to unknown folder")
		newKey = fmt.Sprintf("unknown/%s.jpg", fmt.Sprintf("%x", md5.Sum([]byte(key))))
		command = "unknown"
	} else {
		userID = *rekResp.FaceMatches[0].Face.ExternalImageId
		newKey = fmt.Sprintf("detected/%s/%s.jpg", userID, fmt.Sprintf("%x", md5.Sum([]byte(key))))
		log.Printf("face found, moving to %s", newKey)
		log.Printf("SearchFacesByImageRequest response: %s", rekResp)
		command = "open"
	}

	log.Printf("copying s3 object %s/%s to %s/%s", bucketName, key, bucketName, newKey)
	_, err = s3Client.CopyObjectRequest(&s3.CopyObjectInput{
		CopySource: aws.String(bucketName + "/" + key),
		Bucket:     aws.String(bucketName),
		Key:        aws.String(newKey),
		ACL:        s3.ObjectCannedACLPublicRead,
	}).Send()
	if err != nil {
		return err
	}

	log.Printf("discarding s3 object: %s/%s", bucketName, key)
	_, err = s3Client.DeleteObjectRequest(&s3.DeleteObjectInput{
		Bucket: aws.String(bucketName),
		Key:    aws.String(key),
	}).Send()
	if err != nil {
		return err
	}

	log.Printf("publishing to iot-data topic %s ", iotTopic)
	// get iot endpoint
	iotClient := iot.New(cfg)
	result, err := iotClient.DescribeEndpointRequest(&iot.DescribeEndpointInput{}).Send()
	if err != nil {
		return err
	}
	cfg.EndpointResolver = aws.ResolveWithEndpointURL("https://" + *result.EndpointAddress)

	iotDataClient := iotdataplane.New(cfg)
	p := struct {
		Username string `json:"username"`
		Command  string `json:"command"`
		S3Key    string `json:"s3key"`
	}{
		userID,
		command,
		newKey,
	}

	pp, _ := json.Marshal(p)
	_, err = iotDataClient.PublishRequest(&iotdataplane.PublishInput{
		Payload: pp,
		Topic:   aws.String(iotTopic),
		Qos:     aws.Int64(0),
	}).Send()
	if err != nil {
		return err
	}

	return nil
}

