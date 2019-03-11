
ENVIRONMENT        ?= prod
PROJECT            =  itops
STACK_NAME         =  concierge
ARTIFACTS_BUCKET   =  bucket-name-for-lambda-deployment
AWS_DEFAULT_REGION ?= us-east-1

DEPLOY_DEPS = source/guess/deployment.zip source/train/deployment.zip source/unknown/deployment.zip source/find-person/deployment.zip

sam_package = aws cloudformation package \
                --template-file sam.yaml \
                --output-template-file dist/sam.yaml \
                --s3-bucket $(ARTIFACTS_BUCKET)

sam_deploy = aws cloudformation deploy \
                --template-file dist/sam.yaml \
                --stack-name $(STACK_NAME) \
		--region $(AWS_DEFAULT_REGION) \
                --parameter-overrides \
                        $(shell cat parameters.conf) \
                --capabilities CAPABILITY_IAM \
                --no-fail-on-empty-changeset

all: $(DEPLOY_DEPS)

source/guess/deployment.zip: source/guess/main.go
	cd source/guess; GOOS=linux go build -ldflags="-s -w" -o main && zip deployment.zip main

source/unknown/deployment.zip: source/unknown/main.go
	cd source/unknown; GOOS=linux go build -ldflags="-s -w" -o main && zip deployment.zip main

source/train/deployment.zip: source/train/main.go
	cd source/train; GOOS=linux go build -ldflags="-s -w" -o main && zip deployment.zip main

source/find-person/deployment.zip: source/find-person/find_person.py
	cd source/find-person; mkdir dist \

source/find-person/dist:
	mkdir source/find-person/dist

source/find-person/dist/deployment.zip: source/find-person/find_person.py source/find-person/dist
	cd source/find-person \
		&& cp find_person.py dist/ \
		&& cd dist; zip deployment.zip *

source/trigger-open/deployment.zip: source/trigger-open/trigger_open.py
	docker run -v ${PWD}/source/trigger-open:/app -w /app -it python:2.7-alpine sh -c "pip install -r requirements.txt -t ./dist; chmod -R 777 dist"
		cd source/trigger-open && cp trigger_open.py dist/ \
		&& cd dist/ && zip -r deployment.zip *

dist:
	@mkdir -p dist

deploy: all dist
	# sam
	$(call sam_package)
	$(call sam_deploy)

clean:
	@rm -rf source/*/main source/*/deployment.zip source/*/dist dist


