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
      elif status == 'success':
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
    hs100 = json.loads(configJson)
    self.enabled = hs100['Enabled']
    self.ip = hs100['IP']
    self.plug = SmartPlug(self.ip)
    logger.info('new plug name:%s ip:%s' % (self.name, self.ip))
    #logger.info("Full sysinfo: %s" % pf(greenPlug.get_sysinfo()))

  def indicate(self):
    if self.enabled:
      logger.info('plug:%s turn on' % self.name)
      #self.plug.turn_on()

  def off(self):
    if self.enabled:
      logger.info('plug:%s turn off' % self.name)
      #self.plug.turn_off()
 
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
    logger.info('new photon name:%s deviceId:%s accessToken:%s function:%s' % (self.name, self.deviceId,self.accessToken, self.functionName))

  def updateStatus(self, status):
    if self.enabled:
      logger.info('photon %s status:%s' % (self.name, status))
      #self.sendCall(status)

  def sendCall(self, argValue):
    target_url ="https://api.particle.io/v1/devices/%s/%s?access_token=%s" % (deviceId, functionName, accessToken)

    data = {
      'arg': argValue
    }
    r = requests.post(target_url, data=data)
    logger.info('photon %s response:%s' % (self.name, r.text))


#
# scan jenkins job status and indicate summary results
#
class JenkinsScanner(object):
  def __init__(self, config):
    self.config = config
    self.jenkinsServer = self.config.get('Jenkins', 'Server')
    self.jenkinsPort = self.config.get('Jenkins', 'Port')
    self.jenkinsView = self.config.get('Jenkins', 'View')
    self.jenkinsUrl='http://%s:%s/view/%s/api/json?pretty=true' % (self.jenkinsServer, self.jenkinsPort, self.jenkinsView)

    self.startBusinessHour = self.config.getint('Hours', 'Start')
    self.endBusinessHour = self.config.getint('Hours', 'End')

    self.statusMap = dict(self.config.items('JobStatus'))
    self.buildHolidays = holidays.UnitedStates()

    self.indicator = JenkinsIndicator(self.config)
    self.prev_failed_jobs = set()

    self.failing_jobs = set()
    self.good_jobs = set()
    self.building_jobs = set()

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

  def analyzeJob(self, job):
    jobColor = job['color']
    name = job['name']
    jobStatus = self.statusMap[jobColor]

    if jobStatus == 'failing':
      self.failing_jobs.add(name)
    elif jobStatus == 'success':
      self.good_jobs.add(name)
    elif jobStatus == 'building':
      self.building_jobs.add(name)
    else:
      self.other_jobs.add(name)

    #logger.info('job:%s color:%s status:%s' % (name, jobColor, jobStatus))

  #
  # scan all jobs and determine status
  def scanJobs(self):
    logger.info(' about to query url: %s' % self.jenkinsUrl)
    jenkins_status = json.load(urllib2.urlopen(self.jenkinsUrl))
    jobs = jenkins_status['jobs']

    # append bad jobs to prev_failed_jobs bad jobs

    # clear out and re-scan
    self.failing_jobs = set()
    self.good_jobs = set()
    self.building_jobs = set()
    self.other_jobs = set()

    # sort current job status into lists
    for job in jobs:
      self.analyzeJob(job)

    # add failing jobs to failed list
    self.prev_failed_jobs.update(self.failing_jobs)

    # only remove from failed list if success
    self.prev_failed_jobs.difference_update(self.good_jobs)

  #
  # summarize all jobs into a single status value
  def summarizeJobs(self):
    if self.isBusinessHours():
      # if any job has failed and not yet succeeded again
      if len(self.prev_failed_jobs) > 0:
        logger.info('some jobs failed:%s' % self.prev_failed_jobs)
        self.indicator.indicateStatus('failure')
      else:
        logger.info('nothing failed building jobs:%s' % self.building_jobs)
        self.indicator.indicateStatus('success')
    else:
      logger.info('outside of business hours')
      self.indicator.indicateStatus('off')

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
  scanner.scanJobs()
  scanner.summarizeJobs()
  time.sleep(waitTime)
