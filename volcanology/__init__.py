import logging
import json
import ConfigParser
import urllib2
import time
import datetime
import requests
import sys
import holidays
import socket
import base64
from pprint import pformat as pf
from logging.config import fileConfig

fileConfig('config/logging_config.ini')
logger = logging.getLogger()


def main():
  logger.info('startup volcanology')

  #
  # main loop
  #
  waitTime = 30
  scanner = JenkinsScanner()
  while True:
    try:
      scanner.scanJobs()
      newStatus = scanner.summarizeJobs()
      scanner.indicateStatus(newStatus)
    except: # catch exceptions
        logger.exception("exception in loop" )
    time.sleep(waitTime)

#
# takes summary of jenkins status and communicates to a series of external indicators
#
class JenkinsIndicator(object):

  def __init__(self, config):
    self.config = config
    self.statusTrackers = dict()
    self.indicators = dict()
    self.indicatorsEnabled = config.getboolean("Indicators", "Enabled")

    self.failureIndicators = json.loads(config.get("Indicators","Failure"))
    self.successIndicators = json.loads(config.get("Indicators","Success"))
    self.statusIndicators = json.loads(config.get("Indicators","Status"))

    self.loadPhotonStatus()
    self.loadHS100Plugs()

  # 
  # load photon status objects from config
  def loadPhotonStatus(self):
    for statusName in dict(self.config.items(PhotonStatus.configSection)):
      logger.info('loading photon status:%s' % statusName)
      curStatus = PhotonStatus(statusName, self.config)
      self.statusTrackers[statusName] = curStatus

  # 
  # load hs100 plug objects from config
  def loadHS100Plugs(self):
    for indicatorName in dict(self.config.items(HS100Plug.configSection)):
      logger.info('loading hs100 indicator:%s' % indicatorName)
      curIndicator = HS100Plug(indicatorName, self.config)
      self.indicators[indicatorName] = curIndicator

  #
  # indicate status to plugs and photons
  def indicateStatus(self, status):
    logger.info('indicating overall status:%s' % status)
    if self.indicatorsEnabled:
      if status == 'failure':
        #
        # turn on all the things that indicate failure
        for curInd in self.failureIndicators:
          self.indicators[curInd].indicate()
        #
        # turn off all the things that indicate success
        for curInd in self.successIndicators:
          self.indicators[curInd].off()
      elif status == 'success' or status == 'successStreak':
        #
        # turn on all the things that indicate success
        for curInd in self.successIndicators:
          self.indicators[curInd].indicate()
        #
        # turn off all the things that indicate failure
        for curInd in self.failureIndicators:
          self.indicators[curInd].off()
      elif status == 'off':
        #
        # turn off all the things 
        for curInd in self.indicators:
          self.indicators[curInd].off()
      else:
        logger.info('unknown status:%s' % status)
  
      #
      # update all status trackers
      for curTracker in self.statusTrackers:
        self.statusTrackers[curTracker].updateStatus(status)
    else:
      logger.info('indicators disabled')

#
# control a TP Link wifi outlet
#
class HS100Plug(object):
  turnOn='AAAAKtDygfiL/5r31e+UtsWg1Iv5nPCR6LfEsNGlwOLYo4HyhueT9tTu36Lfog=='
  turnOff='AAAAKtDygfiL/5r31e+UtsWg1Iv5nPCR6LfEsNGlwOLYo4HyhueT9tTu3qPeow=='
  plugPort=9999

  configSection = 'HS100Plugs'

  def netcat(self, hostname, port, content):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((hostname, port))
    s.sendall(content)
    s.shutdown(socket.SHUT_WR)
    while 1:
        data = s.recv(1024)
        if data == "":
            break
    s.close()

  def __init__(self, name, config):
    self.name = name
    self.config = config
    configJson = self.config.get(HS100Plug.configSection, self.name) 
    hs100config = json.loads(configJson)
    self.enabled = hs100config['Enabled']
    self.ip = hs100config['IP']
    logger.debug('new plug name:%s ip:%s' % (self.name, self.ip))

  def indicate(self):
    if self.enabled:
      logger.debug('plug:%s turn on' % self.name)
      try:
        self.netcat(self.ip, self.plugPort, base64.b64decode(self.turnOn) ) 
      except: # catch *all* exceptions
        logger.exception("exception in indicate")

  def off(self):
    if self.enabled:
      logger.debug('plug:%s turn off' % self.name)
      try:
        self.netcat(self.ip, self.plugPort, base64.b64decode(self.turnOff) ) 
      except: # catch *all* exceptions
        logger.exception("exception in off" )
 
#
# control bubble machine via particle.io photon
#
class PhotonStatus(object):
  configSection = 'PhotonStatus'
  def __init__(self, name, config):
    self.name = name
    self.config = config
    configJson = self.config.get(PhotonStatus.configSection, self.name) 
    photon = json.loads(configJson)
    self.enabled = photon['Enabled']
    self.deviceId = photon['DeviceId']
    self.accessToken = photon['AccessToken']
    self.functionName = photon['Function']
    logger.debug('new photon name:%s deviceId:%s accessToken:%s function:%s' % (self.name, self.deviceId,self.accessToken, self.functionName))

  def updateStatus(self, status):
    if self.enabled:
      logger.debug('photon %s status:%s' % (self.name, status))
      self.callFunction(status)

  def callFunction(self, argValue):
    target_url ="https://api.particle.io/v1/devices/%s/%s?access_token=%s" % (self.deviceId, self.functionName, self.accessToken)

    data = {
      'arg': argValue
    }
    r = requests.post(target_url, data=data)
    logger.debug('photon %s response:%s' % (self.name, r.text))

class JenkinsServer(object):
  def __init__(self, config):
    self.config = config
    self.jenkinsServer = self.config.get('Jenkins', 'Server')
    self.jenkinsPort = self.config.get('Jenkins', 'Port')
    self.jenkinsView = self.config.get('Jenkins', 'View')
    self.jenkinsUrl='http://%s:%s/view/%s/api/json?pretty=true' % (self.jenkinsServer, self.jenkinsPort, self.jenkinsView)

  def getJobs(self):
    logger.debug(' about to query url: %s' % self.jenkinsUrl)
    jenkinsStatus = json.load(urllib2.urlopen(self.jenkinsUrl))
    jobs = jenkinsStatus['jobs']
    return jobs

class CategorizedJenkinsJobs(object):
  def __init__(self, config):
    self.config = config
    self.statusMap = dict(self.config.items('JobStatus'))
    self.reset()

  def reset(self):
    self.failingJobs = set()
    self.successJobs = set()
    self.buildingJobs = set()
    self.otherJobs = set()

  def categorizeJob(self, job):
    jobColor = job['color']
    name = job['name']
    jobStatus = self.statusMap[jobColor]

    if jobStatus == 'failing':
      self.failingJobs.add(name)
    elif jobStatus == 'success':
      self.successJobs.add(name)
    elif jobStatus == 'building':
      self.buildingJobs.add(name)
    else:
      self.otherJobs.add(name)

    #logger.info('job:%s color:%s status:%s' % (name, jobColor, jobStatus))
class ScannerStatus(object):
  def __init__(self):
    self.failed = set()
    self.building = set()
    self.successCount = dict()
    self.minSuccessStreak = 6

  def trackBuilding(self, categorizer):
    self.building = categorizer.buildingJobs

  def trackFailed(self, categorizer):
    # add failing jobs to prev failed list
    self.failed.update(categorizer.failingJobs)

    # remove succeeding jobs from failed list
    self.failed.difference_update(categorizer.successJobs)

  #
  # if a job was previously building, is not currently building, and is success
  # then increment success count
  def trackConsecutiveSuccess(self, categorizer):
    # if any job is failing, reset all counts
    if len(self.failed) > 0:
      self.successCount = dict()
    else:
      for curJob in self.building:
        # if a job was building 
        if not curJob in categorizer.buildingJobs:
          # and has now succeeded, increment the count
          if curJob in categorizer.successJobs:
            if curJob in self.successCount:
              self.successCount[curJob] = self.successCount[curJob] + 1
            else:
              self.successCount[curJob] = 1
            logger.debug('incremented success count for job:%s count:%d' % (curJob, self.successCount[curJob]))
          else:
            self.successCount[curJob] = 0
  #
  # check for any job with a success streak
  #
  def detectSuccessStreak(self):
    for curJob in self.successCount.keys():
      if self.successCount[curJob] > self.minSuccessStreak:
        # reset to zero to earn next streak
        self.successCount[curJob] = 0
        return True
    return False

#
# scan jenkins job status and indicate summary results
#
class JenkinsScanner(object):
  def __init__(self):
    self.config = self.loadConfig()
    self.jenkinsServer = JenkinsServer(self.config)

    self.startBusinessHour = self.config.getint('Hours', 'Start')
    self.endBusinessHour = self.config.getint('Hours', 'End')
    self.buildHolidays = holidays.UnitedStates()

    self.indicator = JenkinsIndicator(self.config)
    self.categorizer = CategorizedJenkinsJobs(self.config)
    self.scanStatus = ScannerStatus()


  def loadConfig(self):
    # read config items from file
    config = ConfigParser.ConfigParser()
    configFile = "config/volcanology.ini"
    if len(sys.argv) > 1 and len(sys.argv[1]) > 0:
      configFile = sys.argv[1]
    config.read(configFile)
    return config

  def isBusinessHours(self):
    now = datetime.datetime.now()

    if now in self.buildHolidays:
      logger.info('build holiday')
      return False

    dayNum = datetime.datetime.today().weekday()
    if dayNum >= 5:
      logger.info('build weekend')
      return False

    if now.hour >= self.startBusinessHour and now.hour <= self.endBusinessHour:
      return True
    else:
      logger.info('build outside of hours')
      return False

  #
  # scan all jobs and determine status
  def scanJobs(self):
    # remember previous building jobs
    self.scanStatus.trackBuilding(self.categorizer)

    # clear out category lists 
    self.categorizer.reset()

    # categorize current job status into lists
    jobs = self.jenkinsServer.getJobs()
    for job in jobs:
      self.categorizer.categorizeJob(job)

    # track failing jobs
    self.scanStatus.trackFailed(self.categorizer)

    # count the consecutive successes to detect streaks
    self.scanStatus.trackConsecutiveSuccess(self.categorizer)
  
  #
  # summarize all jobs into a single status value
  def summarizeJobs(self):
    if self.isBusinessHours():
      # if any job is failing (or has recently failed and is still building)
      if len(self.scanStatus.failed) > 0:
        logger.info('some jobs failed:%s' % self.scanStatus.failed)
        newStatus = 'failure'
      else:
        logger.debug('nothing failed. building jobs:%s' % self.categorizer.buildingJobs)
        if self.scanStatus.detectSuccessStreak():
          newStatus = 'successStreak'
        else:
          newStatus = 'success'
    else:
      logger.info('outside of business hours')
      newStatus = 'off'

    return newStatus

  def indicateStatus(self, newStatus):
    # send the new status to all of the devices
    self.indicator.indicateStatus(newStatus)

main()
