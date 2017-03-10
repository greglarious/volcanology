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

# 
# read config items from file
# 
Config = ConfigParser.ConfigParser()
config_file = "volcanology.ini"
if len(sys.argv) > 1 and len(sys.argv[1]) > 0:
  config_file = sys.argv[1]
Config.read(config_file)

#
# takes summary of jenkins status and communicates to a series of external indicators
#
class JenkinsIndicator(object):

  def __init__(self):
    self.statusTrackers = dict()
    self.indicators = dict()
    self.indicatorsEnabled = Config.getboolean("Indicators", "Enabled")

    self.failureIndicators = json.loads(Config.get("Indicators","Failure"))
    self.successIndicators = json.loads(Config.get("Indicators","Success"))
    self.statusIndicators = json.loads(Config.get("Indicators","Status"))

    self.loadPhotonStatus()
    self.loadHS100Plugs()

  # 
  # load photon status objects from config
  def loadPhotonStatus(self):
    for statusName in dict(Config.items(PhotonStatus.PhotonConfigSection)):
      print('loading photon status:%s' % statusName)
      curStatus = PhotonStatus(statusName)
      self.statusTrackers[statusName] = curStatus

  # 
  # load hs100 plug objects from config
  def loadHS100Plugs(self):
    for indicatorName in dict(Config.items(HS100Plug.HS100ConfigSection)):
      print('loading hs100 indicator:%s' % indicatorName)
      curIndicator = HS100Plug(indicatorName)
      self.indicators[indicatorName] = curIndicator

  #
  # indicate status to plugs and photons
  def indicateStatus(self, status):
    print('indicating overall status:%s' % status)
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
        print('unknown status:%s' % status)
  
      #
      # update all status trackers
      for curTracker in self.statusTrackers:
        self.statusTrackers[curTracker].updateStatus(status)
    else:
      print('indicators disabled')

#
# control a TP Link wifi outlet
#
class HS100Plug(object):
  HS100ConfigSection = 'HS100Plugs'
  def __init__(self, name):
    self.name = name
    configJson = Config.get(HS100Plug.HS100ConfigSection, self.name) 
    hs100 = json.loads(configJson)
    self.enabled = hs100['Enabled']
    self.ip = hs100['IP']
    self.plug = SmartPlug(self.ip)
    print('new plug name:%s ip:%s' % (self.name, self.ip))
    #print("Full sysinfo: %s" % pf(greenPlug.get_sysinfo()))

  def indicate(self):
    if self.enabled:
      print('plug:%s turn on' % self.name)
      #self.plug.turn_on()

  def off(self):
    if self.enabled:
      print('plug:%s turn off' % self.name)
      #self.plug.turn_off()
 
#
# control bubble machine via particle.io photon
#
class PhotonStatus(object):
  PhotonConfigSection = 'PhotonStatus'
  def __init__(self, name):
    self.name = name
    configJson = Config.get(PhotonStatus.PhotonConfigSection, self.name) 
    photon = json.loads(configJson)
    self.enabled = photon['Enabled']
    self.DEVICE_ID = photon['DeviceId']
    self.ACCESS_TOKEN = photon['AccessToken']
    self.FUNC_NAME = photon['Function']
    print('new photon name:%s deviceId:%s accessToken:%s function:%s' % (self.name, self.DEVICE_ID,self.ACCESS_TOKEN, self.FUNC_NAME))

  def updateStatus(self, status):
    if self.enabled:
      print('photon %s status:%s' % (self.name, status))
      #self.sendCall(status)

  def sendCall(self, argValue):
    target_url ="https://api.particle.io/v1/devices/%s/%s?access_token=%s" % (DEVICE_ID, FUNC_NAME, ACCESS_TOKEN)

    data = {
      'arg': argValue
    }
    r = requests.post(target_url, data=data)
    print('photon %s response:%s' % (self.name, r.text))


#
# scan jenkins job status and indicate summary results
#
class JenkinsScanner(object):
  JENKINS_SERVER = Config.get('Jenkins', 'Server')
  JENKINS_PORT = Config.get('Jenkins', 'Port')
  JENKINS_VIEW_NAME = Config.get('Jenkins', 'View')
  JENKINS_STATUS_URL='http://%s:%s/view/%s/api/json?pretty=true' % (JENKINS_SERVER, JENKINS_PORT, JENKINS_VIEW_NAME)

  MIN_BUS_HOUR = Config.getint('Hours', 'Start')
  MAX_BUS_HOUR = Config.getint('Hours', 'End')

  statusMap = dict(Config.items('JobStatus'))
  buildHolidays = holidays.UnitedStates()

  indicator = JenkinsIndicator()
  prev_failed_jobs = set()

  failing_jobs = set()
  good_jobs = set()
  building_jobs = set()

  def isBusinessHours(self):
    now = datetime.datetime.now()

    if now in self.buildHolidays:
      print('build holiday')
      return False

    dayNum = datetime.datetime.today().weekday()
    if dayNum >= 5:
      print('build weekend')
      return False

    if now.hour >= self.MIN_BUS_HOUR and now.hour <= self.MAX_BUS_HOUR:
      return True
    else:
      print('build outside of hours')
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

    #print('job:%s color:%s status:%s' % (name, jobColor, jobStatus))

  #
  # scan all jobs and determine status
  def scanJobs(self):
    print(' about to query url: %s' % self.JENKINS_STATUS_URL)
    jenkins_status = json.load(urllib2.urlopen(self.JENKINS_STATUS_URL))
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
        print('failed jobs:%s' % self.prev_failed_jobs)
        print('building jobs:%s' % self.building_jobs)
        self.indicator.indicateStatus('failure')
      else:
        print('building jobs:%s' % self.building_jobs)
        self.indicator.indicateStatus('success')
    else:
      self.indicator.indicateStatus('off')

#
# main loop
#
WAIT_TIME = 30
scanner = JenkinsScanner()
while True:
  scanner.scanJobs()
  scanner.summarizeJobs()
  time.sleep(WAIT_TIME)
