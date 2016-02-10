#!/usr/bin/env python

# Import standard python libs
import sys, os, time
from datetime import datetime
try:
    from urllib.request import urlopen
except ImportError:
    from urllib2 import urlopen
import signal
import threading
import json
import random
import logging

# Import third-party libs
from logger import Logger
try:
    from daemon import runner
    HAS_DAEMON=True
except ImportError as e:
    sys.stderr.write('Import Error: {0}\n'.format(e))
    sys.exit(2)
try:
    import twitter
    HAS_TWITTER=True
except ImportError as e:
    log.info('Twitter API library not found, will not publish tweets.\n')
    HAS_TWITTER=False

class Monitor():
    def __init__(self):
        self.lastPingCheck = None
        self.lastSpeedTest = None

    def run(self):
        if not self.lastPingCheck or (datetime.now() - self.lastPingCheck).total_seconds() >= 60:
            self.runPingTest()
            self.lastPingCheck = datetime.now()

        if not self.lastSpeedTest or (datetime.now() - self.lastSpeedTest).total_seconds() >= 3600:
            self.runSpeedTest()
            self.lastSpeedTest = datetime.now()

    def runPingTest(self):
        pingThread = PingTest()
        pingThread.start()

    def runSpeedTest(self):
        speedThread = SpeedTest()
        speedThread.start()

class PingTest(threading.Thread):
    def __init__(self, numPings=3, pingTimeout=2, maxWaitTime=6):
        super(PingTest, self).__init__()
        self.numPings = numPings
        self.pingTimeout = pingTimeout
        self.maxWaitTime = maxWaitTime
        self.config = json.load(open('./config.json'))
        self.logger = Logger(self.config['log']['type'], { 'filename': self.config['log']['files']['ping'] })

    def run(self):
        pingResults = self.doPingTest()
        self.logPingResults(pingResults)

    def doPingTest(self):
        log.debug('Performing PingTest')
        response = os.system("ping -c %s -W %s -w %s 8.8.8.8 > /dev/null 2>&1" % (self.numPings, (self.pingTimeout * 1000), self.maxWaitTime))
        success = 0
        if response == 0:
            success = 1
        return { 'date': datetime.now(), 'success': success }

    def logPingResults(self, pingResults):
        log.debug('Logging Ping Results')
        self.logger.log([ pingResults['date'].strftime('%Y-%m-%d %H:%M:%S'), str(pingResults['success'])])

class SpeedTest(threading.Thread):
    def __init__(self):
        super(SpeedTest, self).__init__()
        self.config = json.load(open('./config.json'))
        self.logger = Logger(self.config['log']['type'], { 'filename': self.config['log']['files']['speed'] })

    def run(self):
        speedTestResults = self.doSpeedTest()
        self.logSpeedTestResults(speedTestResults)
        if HAS_TWITTER and 'twitter' in self.config:
            log.debug('Have Twitter and sending results')
            self.tweetResults(speedTestResults)

    def doSpeedTest(self):
        # run a speed test
        log.info('Performing SpeedTest')
        result = os.popen("speedtest-cli --simple --share").read()
        if 'Cannot' in result:
            log.info('Speedtest failed to return results')
            return { 'date': datetime.now(), 'uploadResult': 0, 'downloadResult': 0, 'ping': 0, 'imageResult': None }

        # Result:
        # Ping: 529.084 ms
        # Download: 0.52 Mbit/s
        # Upload: 1.79 Mbit/s
        # Share results: http://www.speedtest.net/result/1234567890.png

        resultSet = result.splitlines()
        pingResult = resultSet[0]
        downloadResult = resultSet[1]
        uploadResult = resultSet[2]
        imageResult = resultSet[3]

        pingResult = float(pingResult.replace('Ping: ', '').replace(' ms', ''))
        downloadResult = float(downloadResult.replace('Download: ', '').replace(' Mbit/s', ''))
        uploadResult = float(uploadResult.replace('Upload: ', '').replace(' Mbit/s', ''))
        imageResult = str(imageResult.replace('Share results: ', ''))
        return { 'date': datetime.now(), 'uploadResult': uploadResult, 'downloadResult': downloadResult, 'ping': pingResult, 'imageResult': imageResult }

    def logSpeedTestResults(self, speedTestResults):
        log.debug('Logging SpeedTest results')
        self.logger.log([ speedTestResults['date'].strftime('%Y-%m-%d %H:%M:%S'), str(speedTestResults['uploadResult']), str(speedTestResults['downloadResult']), str(speedTestResults['ping']), str(speedTestResults['imageResult']) ])


    def tweetResults(self, speedTestResults):
        log.debug('Preparing to tweet results')
        thresholdMessages = self.config['tweetThresholds']
        message = None
        media = None
        api = twitter.Api(consumer_key=self.config['twitter']['twitterConsumerKey'],
                        consumer_secret=self.config['twitter']['twitterConsumerSecret'],
                        access_token_key=self.config['twitter']['twitterToken'],
                        access_token_secret=self.config['twitter']['twitterTokenSecret'])
        for (threshold, messages) in thresholdMessages.items():
            threshold = float(threshold)
            if speedTestResults['downloadResult'] < threshold:
                message = messages[random.randint(0, len(messages) - 1)].replace('{tweetTo}', self.config['tweetTo']).replace('{internetSpeed}', self.config['internetSpeed']).replace('{downloadResult}', str(speedTestResults['downloadResult']))

        if speedTestResults['imageResult']:
            media = urlopen(str(speedTestResults['imageResult']))

        if media and message and api:
            status = api.PostMedia(message, media)

        elif message and api:
            status = api.PostUpdate(message)

        if status:
            log.info('Tweet {0} posted'.format(status.id_str))

class SpeedComplainer():
    def __init__(self, stdin='/dev/null', stdout='/dev/null', stderr='/dev/null'):
        self.stdin_path = stdin
        self.stdout_path = stdout
        self.stderr_path = stderr
        self.pidfile_timeout = 5

    def run(self):
        monitor = Monitor()
        while True:
            try:
                monitor.run()
                for i in range(0, 5):
                    time.sleep(1)
            except Exception as e:
                print ('Error: {0}'.format(e))
                sys.exit(1)

if __name__ == '__main__':
    workingDirectory = os.path.dirname(os.path.abspath(__file__))
    fileName, fileExt = os.path.splitext(os.path.basename(__file__))
    pidFilePath = os.path.join(workingDirectory, '{0}.pid'.format(fileName))
    logFilePath = os.path.join(workingDirectory, '{0}.log'.format(fileName))

    app = SpeedComplainer()
    app.pidfile_path = pidFilePath

    log = logging.getLogger("DaemonLog")
    log.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    handler = logging.FileHandler(logFilePath)
    handler.setFormatter(formatter)
    log.addHandler(handler)

    daemon = runner.DaemonRunner(app)
    daemon.daemon_context.working_directory = workingDirectory
    daemon.daemon_context.files_preserve=[handler.stream]
    daemon.daemon_context.umask = 077
    if len(sys.argv) == 2 and 'stop' != sys.argv[1]:
        log.info("======================================")
        log.info("Starting Speed Complainer!")
        log.info("Let's get noisy!")
        log.info("======================================")
    daemon.do_action()
