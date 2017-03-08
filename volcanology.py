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

buildHolidays = holidays.UnitedStates()

#
# control bubble machine via particle.io photon
#
class BubbleMachine(object):
  DEVICE_ID = Config.get('Bubbles', 'DeviceId') 
  ACCESS_TOKEN = Config.get('Bubbles', 'AccessToken') 
  FUNC_NAME ="bubbles"
  def trackSuccess(self):
    print('success bubble')
    self.sendCall("success")

  def trackFailure(self):
    print('failure bubble')
    self.sendCall("failure")

  def sendCall(self, argValue):
    target_url ="https://api.particle.io/v1/devices/%s/%s?access_token=%s" % (DEVICE_ID, FUNC_NAME, ACCESS_TOKEN)

    data = {
      'arg': argValue
    }
    r = requests.post(target_url, data=data)
    print('bubble response:%s' % r.text)

#
# indicate status via lava lamps and bubbles
#
class JenkinsIndicator(object):
  enabled = False

  GREEN_IP = Config.get('Plugs', 'GreenIP1')
  RED_IP = Config.get('Plugs', 'RedIP1')
  RED2_IP = Config.get('Plugs', 'RedIP2')

  green = SmartPlug(GREEN_IP)
  red = SmartPlug(RED_IP)
  red2 = SmartPlug(RED2_IP)
  bubble = BubbleMachine()

  #print("Full sysinfo: %s" % pf(greenPlug.get_sysinfo()))

  def allOff(self):
    if self.enabled:
      self.green.turn_off()
      self.red.turn_off()
      self.red2.turn_off()
      print('all off')

  def indicateGreen(self):
    if self.enabled:
      self.green.turn_on()
      self.red.turn_off()
      self.red2.turn_off()
      self.bubble.trackSuccess()

  def indicateRed(self):
    if self.enabled:
      self.red.turn_on()
      self.red2.turn_on()
      self.green.turn_off()
      self.bubble.trackFailure()

  # status: off success failure
  def setStatus(self, status):
    print('lamp status is: %s' % status)
    if status == "off":
     self.allOff()
    elif status == "success":
     self.indicateGreen()
    elif status == "failure":
     self.indicateRed()

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

  indicator = JenkinsIndicator()
  prev_failed_jobs = set()

  failing_jobs = set()
  good_jobs = set()
  building_jobs = set()

  def isBusinessHours(self):
    now = datetime.datetime.now()

    if now in buildHolidays:
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
    status = job['color']
    name = job['name']
    if status == 'red':
      self.failing_jobs.add(name)
    elif status == 'blue':
      self.good_jobs.add(name)
    elif status == 'notbuilt':
      print('ignore notbuilt job:%s' % name)
    elif status == 'disabled':
      print('ignore disabled job:%s' % name)
    elif status == 'blue_anime':
      self.building_jobs.add(name)
    elif status == 'red_anime':
      # building but was previously broken
      self.building_jobs.add(name)
    else:
      print('saw unknown status:%s job:%s' % (status, name))

  def scanJobs(self):
    print(' about to query url: %s' % self.JENKINS_STATUS_URL)
    jenkins_status = json.load(urllib2.urlopen(self.JENKINS_STATUS_URL))
    jobs = jenkins_status['jobs']

    # append bad jobs to prev_failed_jobs bad jobs

    # clear out and re-scan
    self.failing_jobs = set()
    self.good_jobs = set()
    self.building_jobs = set()

    # sort current job status into lists
    for job in jobs:
      self.analyzeJob(job)

    # add failing jobs to failed list
    self.prev_failed_jobs.update(self.failing_jobs)

    # only remove from failed list if success
    self.prev_failed_jobs.difference_update(self.good_jobs)

  def summarizeJobs(self):
    if self.isBusinessHours():
      # if any job has failed and not yet succeeded again
      if len(self.prev_failed_jobs) > 0:
        print('failed jobs:%s' % self.prev_failed_jobs)
        print('building jobs:%s' % self.building_jobs)
        self.indicator.setStatus('failure')
      else:
        print('building jobs:%s' % self.building_jobs)
        self.indicator.setStatus('success')
    else:
      self.indicator.setStatus('off')

#
# main loop
#
WAIT_TIME = 30
scanner = JenkinsScanner()
while True:
  scanner.scanJobs()
  scanner.summarizeJobs()
  time.sleep(WAIT_TIME)
