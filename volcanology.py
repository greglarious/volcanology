import logging
import json
import ConfigParser
import urllib2
import time
import datetime
import requests
import sys
import holidays
from pyHS100 import SmartPlug
from pprint import pformat as pf
from logging.config import fileConfig

fileConfig('logging_config.ini')
logger = logging.getLogger()

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
    for statusName in dict(config.items(PhotonStatus.configSection)):
      logger.info('loading photon status:%s' % statusName)
      curStatus = PhotonStatus(statusName, self.config)
      self.statusTrackers[statusName] = curStatus

  # 
  # load hs100 plug objects from config
  def loadHS100Plugs(self):
    for indicatorName in dict(config.items(HS100Plug.configSection)):
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
  configSection = 'HS100Plugs'
  def __init__(self, name, config):
    self.name = name
    self.config = config
    configJson = self.config.get(HS100Plug.configSection, self.name) 
    hs100config = json.loads(configJson)
    self.enabled = hs100config['Enabled']
    self.ip = hs100config['IP']
    self.plug = SmartPlug(self.ip)
    logger.debug('new plug name:%s ip:%s' % (self.name, self.ip))
    #logger.info("Full sysinfo: %s" % pf(greenPlug.get_sysinfo()))

  def indicate(self):
    if self.enabled:
      logger.debug('plug:%s turn on' % self.name)
      try:
        self.plug.turn_on()
      except: # catch *all* exceptions
        logger.exception("exception in indicate")

  def off(self):
    if self.enabled:
      logger.debug('plug:%s turn off' % self.name)
      try:
        self.plug.turn_off()
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
#
# scan jenkins job status and indicate summary results
#
class JenkinsScanner(object):
  def __init__(self, config):
    self.config = config
    self.jenkinsServer = JenkinsServer(self.config)

    self.startBusinessHour = self.config.getint('Hours', 'Start')
    self.endBusinessHour = self.config.getint('Hours', 'End')
    self.buildHolidays = holidays.UnitedStates()

    self.indicator = JenkinsIndicator(self.config)
    self.prevFailed = set()
    self.prevBuilding = set()
    self.successCount = set()
    self.categorizer = CategorizedJenkinsJobs(self.config)


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
    self.prevBuilding = self.categorizer.buildingJobs

    # clear out category lists 
    self.categorizer.reset()

    # categorize current job status into lists
    jobs = self.jenkinsServer.getJobs()
    for job in jobs:
      self.categorizer.categorizeJob(job)

    # add failing jobs to prev failed list
    self.prevFailed.update(self.categorizer.failingJobs)

    # remove succeeding jobs from failed list
    self.prevFailed.difference_update(self.categorizer.successJobs)

    # count the consecutive successes to detect streaks
    self.trackConsecutiveSuccess()

  #
  # if a job was previously building, is not currently building, and is success
  # then increment success count
  def trackConsecutiveSuccess(self):
    # if any job is failing, reset all counts
    if len(self.prevFailed) > 0:
      self.successCount = set()
    else:
      for curJob in self.prevBuilding:
        # if a job was building 
        if not curJob in self.categorizer.buildingJobs.keys():
          # and has now succeeded, increment the count
          if curJob in self.categorizer.successJobs.keys():
            successCount[curJob] = successCount[curJob] + 1
          else:
            successCount[curJob] = 0
  
  #
  # check for any job with a success streak
  #
  def detectSuccessStreak(self):
    minSuccessStreak = 2
    for curJob in successCount:
      if successCount[curJob] > minSuccessStreak:
        successCount[curJob] = 0
        return True
    return False

  #
  # summarize all jobs into a single status value
  def summarizeJobs(self):

    if self.isBusinessHours():
      # if any job is failing (or has recently failed and is still building)
      if len(self.prevFailed) > 0:
        logger.info('some jobs failed:%s' % self.prevFailed)
        newStatus = 'failure'
      else:
        logger.debug('nothing failed. building jobs:%s' % self.categorizer.buildingJobs)
        if detectSuccessStreak():
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
# 
# read config items from file
# 
config = ConfigParser.ConfigParser()
configFile = "volcanology.ini"
if len(sys.argv) > 1 and len(sys.argv[1]) > 0:
  configFile = sys.argv[1]
config.read(configFile)

#
# main loop
#
waitTime = 30
scanner = JenkinsScanner(config)
while True:
  try:
    scanner.scanJobs()
    newStatus = scanner.summarizeJobs()
    scanner.indicateStatus(newStatus)
  except: # catch *all* exceptions
      logger.exception("exception in loop" )
  time.sleep(waitTime)
