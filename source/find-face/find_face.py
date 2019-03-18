#*****************************************************
#                                                    *
# Copyright 2018 Amazon.com, Inc. or its affiliates. *
# All Rights Reserved.                               *
#                                                    *
#*****************************************************
""" A sample lambda for face detection"""
from threading import Thread, Event
import os
import json
import numpy as np
import awscam
import cv2
from botocore.session import Session
import datetime
import time

# Setup the S3 client
is_deeplens_upside_down = os.environ['IS_DEEPLENS_UPSIDE_DOWN']
print_debug = True if 'DEBUG' in os.environ else False
fullres_local_stream = True if 'STREAM_FULLRES' in os.environ else False
stream_resolution = os.environ['STREAM_RESOLUTION'] if 'STREAM_RESOLUTION' in os.environ else '480p'
overlay = True if 'OVERLAY' in os.environ else False
# Set the threshold for detection
detection_threshold = float(os.environ['THRESHOLD']) if 'THRESHOLD' in os.environ else 0.25

class LocalDisplay(Thread):
    """ Class for facilitating the local display of inference results
        (as images). The class is designed to run on its own thread. In
        particular the class dumps the inference results into a FIFO
        located in the tmp directory (which lambda has access to). The
        results can be rendered using mplayer by typing:
        mplayer -demuxer lavf -lavfdopts format=mjpeg:probesize=32 /tmp/results.mjpeg
    """
    def __init__(self, resolution):
        """ resolution - Desired resolution of the project stream """
        # Initialize the base class, so that the object can run on its own
        # thread.
        super(LocalDisplay, self).__init__()
        # List of valid resolutions
        RESOLUTION = {'1080p' : (1920, 1080), '720p' : (1280, 720), '480p' : (858, 480)}
        if resolution not in RESOLUTION:
            raise Exception("Invalid resolution")
        self.resolution = RESOLUTION[resolution]
        # Initialize the default image to be a white canvas. Clients
        # will update the image when ready.
        self.frame = cv2.imencode('.jpg', 255*np.ones([640, 480, 3]))[1]
        self.stop_request = Event()

    def run(self):
        """ Overridden method that continually dumps images to the desired
            FIFO file.
        """
        # Path to the FIFO file. The lambda only has permissions to the tmp
        # directory. Pointing to a FIFO file in another directory
        # will cause the lambda to crash.
        result_path = '/tmp/results.mjpeg'
        # Create the FIFO file if it doesn't exist.
        if not os.path.exists(result_path):
            os.mkfifo(result_path)
        # This call will block until a consumer is available
        with open(result_path, 'w') as fifo_file:
            while not self.stop_request.isSet():
                try:
                    # Write the data to the FIFO file. This call will block
                    # meaning the code will come to a halt here until a consumer
                    # is available.
                    fifo_file.write(self.frame.tobytes())
                except IOError:
                    continue

    def set_frame_data(self, frame):
        """ Method updates the image data. This currently encodes the
            numpy array to jpg but can be modified to support other encodings.
            frame - Numpy array containing the image data tof the next frame
                    in the project stream.
        """
        if fullres_local_stream is False:
            frame = cv2.resize(frame, self.resolution)
        ret, jpeg = cv2.imencode('.jpg', frame)
        if not ret:
            raise Exception('Failed to set frame data')
        self.frame = jpeg

    def join(self):
        self.stop_request.set()

class S3Uploader(Thread):
    def __init__(self):
        Thread.__init__(self)
        self.go = Event()
        self.go.clear()
        self.s3 = Session().create_client('s3')
        self.s3_bucket = os.environ['BUCKET_NAME']

    def run(self):
        while True:
            self.go.wait()
            jpeg_data = self.jpeg_data
            self.go.clear()

            # create a nice s3 file key
            s3_key = datetime.datetime.utcnow().strftime('%Y-%m-%d_%H_%M_%S.%f') + '.jpg'
            filename = "incoming/%s" % s3_key  # the guess lambda function is listening here
            response = self.s3.put_object(Body=jpeg_data.tostring(),Bucket=self.s3_bucket,Key=filename)
            if print_debug is True: print("Uploaded to S3: %s in bucket %s, response %s" % (filename,self.s3_bucket,str(response)))

    def set_frame_data(self, frame):
        dim = frame.shape
        running = self.go.isSet() 
        if len(dim)==3 and dim[0]>0 and dim[1]>0 and running is False:
            encode_param=[int(cv2.IMWRITE_JPEG_QUALITY), 90]  # 90% should be more than enough
            _, jpeg_data = cv2.imencode('.jpg', frame, encode_param)
            self.jpeg_data = jpeg_data
            self.go.set()

def infinite_infer_run():
    """ Entry point of the lambda function"""
    try:
        # This face detection model is implemented as single shot detector (ssd).
        model_type = 'ssd'
        output_map = {1: 'face'}

        # Create a local display instance that will dump the image bytes to a FIFO
        # file that the image can be rendered locally.
        local_display = LocalDisplay(stream_resolution)
        local_display.start()
        overlay_frame = None

        s3_thread = S3Uploader()
        s3_thread.start()

        # The sample projects come with optimized artifacts, hence only the artifact
        # path is required.
        model_path = '/opt/awscam/artifacts/mxnet_deploy_ssd_FP16_FUSED.xml'
        # Load the model onto the GPU.
        print('Loading face detection model')
        model = awscam.Model(model_path, {'GPU': 1})
        print('Face detection model loaded')
        # The height and width of the training set images
        input_height = 300
        input_width = 300
        # Do inference until the lambda is killed.
        while True:
            # Get a frame from the video stream
            ret, frame = awscam.getLastFrame()
            if not ret:
                raise Exception('Failed to get frame from the stream')
            if is_deeplens_upside_down == 'yes':
                frame = cv2.flip( frame, -1 )
            # Resize frame to the same size as the training set.
            frame_resize = cv2.resize(frame, (input_height, input_width))
            # Run the images through the inference engine and parse the results using
            # the parser API, note it is possible to get the output of doInference
            # and do the parsing manually, but since it is a ssd model,
            # a simple API is provided.
            parsed_inference_results = model.parseResult(model_type,
                                                         model.doInference(frame_resize))
            # Compute the scale in order to draw bounding boxes on the full resolution
            # image.
            yscale = float(frame.shape[0]) / float(input_height)
            xscale = float(frame.shape[1]) / float(input_width)
            # Dictionary to be filled with labels and probabilities for MQTT
            cloud_output = {}
            # Get the detected faces and probabilities
            last_person = 0.0
            for obj in parsed_inference_results[model_type]:
                if obj['prob'] > detection_threshold:
                    now = time.time()
                    # Add bounding boxes to full resolution frame
                    xmin = int(xscale * obj['xmin'] * 0.98)
                    xmax = int(xscale * obj['xmax'] * 1.02) % frame.shape[1]
                    ymin = int(yscale * obj['ymin'] * 0.88)
                    ymax = int(yscale * obj['ymax'] * 1.05) % frame.shape[0]
                    # See https://docs.opencv.org/3.4.1/d6/d6e/group__imgproc__draw.html
                    # for more information about the cv2.rectangle method.
                    # Method signature: image, point1, point2, color, and tickness.
                    cv2.rectangle(frame, (xmin, ymin), (xmax, ymax), (255, 165, 20), 10)
                    # Amount to offset the label/probability text above the bounding box.
                    text_offset = 15
                    # See https://docs.opencv.org/3.4.1/d6/d6e/group__imgproc__draw.html
                    # for more information about the cv2.putText method.
                    # Method signature: image, text, origin, font face, font scale, color,
                    # and tickness
                    cv2.putText(frame, '{:.2f}%'.format(obj['prob'] * 100),
                                (xmin, ymin-text_offset),
                                cv2.FONT_HERSHEY_SIMPLEX, 2.5, (255, 165, 20), 6)
                    # Store label and probability to send to cloud
                    cloud_output[output_map[obj['label']]] = obj['prob']

                    # Upload person frame to s3
                    if now-last_person > 2.0:
                        last_person = now
                        cutout = frame[ymin:ymax, xmin:xmax]
                        if cutout is not None and len(cutout.shape)==3 and cutout.shape[0]>0 and cutout.shape[1]>0:
                            s3_thread.set_frame_data(cutout)
                            overlay_y = int(frame.shape[0]/3)
                            scale_factor = overlay_y/float(cutout.shape[0])
                            overlay_x = int(cutout.shape[1]*scale_factor)
                            overlay_frame = cv2.resize(cutout, (overlay_x,overlay_y))

            # Add overlay in lower right corner
            if overlay is True and overlay_frame is not None:
                y_offset = frame.shape[0]-overlay_frame.shape[0]
                x_offset = frame.shape[1]-overlay_frame.shape[1]
                frame[y_offset:frame.shape[0], x_offset:frame.shape[1]] = overlay_frame

            # Set the next frame in the local display stream.
            local_display.set_frame_data(frame)
            # Send results to the cloud
            if len(cloud_output): print(json.dumps(cloud_output))
    except Exception as e:
        print("Crap, something failed: %s" % str(e))

infinite_infer_run()

# This is a dummy handler and will not be invoked
# Instead the code above will be executed in an infinite loop for our example
def function_handler(event, context):
    return
