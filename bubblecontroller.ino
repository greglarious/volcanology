// bubbles earned if failure less than this time
const long MAX_RECOVERY_TIME = 1000 * 60 * 45;

// how long to activate bubbles
const long BUBBLE_ON_TIME = 20000;

// mosfet for on/off of bubble machine
const int bubblePin = D5; 

// when to turn off bubbles
long offTime = 0;

// mark begin of build failure
long failureTime = 0;

void setup() {
pinMode(bubblePin, OUTPUT);
    digitalWrite(bubblePin, LOW);
    Particle.function("bubbles",bubbleToggle);
}

void loop() {
    autoOffBubbleCheck();
}

// initiate bubble sequence for set time
void turnOn() {
    digitalWrite(bubblePin,HIGH);
    offTime = millis() + BUBBLE_ON_TIME;
}

void turnOff() {
    digitalWrite(bubblePin,LOW);
    offTime = 0;
}

// test for auto bubble shutoff
void autoOffBubbleCheck() {
    if (offTime > 0 && millis() > offTime) {
        turnOff();
    }
}

// if success quickly after failure then initiate victory bubble sequence
int successBubbleCheck() {
    if ( (failureTime > 0) && ((millis() - failureTime) < MAX_RECOVERY_TIME) ) {
        failureTime = 0;
        turnOn();
        return 1;
    } else {
        return 0;
    }
}

// receive commands via REST calls
int bubbleToggle(String command) {
    if (command=="on") {
        turnOn();
        return 1;
    }
    else if (command=="off") {
        turnOff();
        return 0;
    }
    else if (command=="failure") {
        failureTime = millis();
        return 0;
    }
    else if (command=="success") {
        return successBubbleCheck();
    }
    else {
        return -1;
    }
}
