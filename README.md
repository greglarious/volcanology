# volcanology
Jenkins build status indicator with lava lamps and bubble machines.

Scans a Jenkins view for list of builds and status.  
- When all builds succeed, activate the "green" indicators
- When builds are failing activate the "red" indicators
- Once a build fails, it has to succeed to qualify for clearing the red status
- includes implementation for controlling a TP Link HS100
- includes implementation for making rest calls to a particle photon
- includes photon script to activate a bubble machine if builds are fixed quickly after failing

## To Do
- [ ] load and instantiate lists of build indicators from config file
- [ ] add more types of wifi smart switches
- [ ] add ITTT integration
- [ ] create Fritzing schematic for bubble machine integration circuit
