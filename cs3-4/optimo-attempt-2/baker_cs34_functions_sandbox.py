#-- Necessary Headers --#
from __future__ import print_function   # For Python 3 compatibility
from scipy.interpolate import interp1d  # To create our splines
from scipy import optimize  # To create our splines
import scipy.spatial.distance as ssd
import matplotlib.pyplot as plt
import numpy as np
import sys
import yaml                             # For reading .yaml files
# For the AEP calculation code
import iea37_aepcalc as iea37aepC
from math import radians as DegToRad    # For converting degrees to radians
from math import log as ln  # For natural logrithm

# Structured datatype for holding coordinate pair
coordinate = np.dtype([('x', 'f8'), ('y', 'f8')])  

# -- Helper Functions --#
# Read in boundary (originally written in MATLAB, needed to be translated)
def getTurbAtrbtCs4YAML(file_name):
    '''Retreive boundary coordinates from the <.yaml> file'''
    # Read in the .yaml file
    with open(file_name, 'r') as f:
        bndrs = yaml.safe_load(f)['boundaries']
        
    ptList3a = bndrs['IIIa']
    ptList3b = bndrs['IIIb']
    ptList4a = bndrs['IVa']
    ptList4b = bndrs['IVb']
    ptList4c = bndrs['IVc']

    # (Convert from <list> to <coordinate> array)
    # Determine how many points we have for the boundary
    numCoords3a = len(ptList3a)
    numCoords3b = len(ptList3b)
    numCoords4a = len(ptList4a)
    numCoords4b = len(ptList4b)
    numCoords4c = len(ptList4c)
    # Initialize the point list array
    coordList3a = np.recarray(numCoords3a, coordinate)
    coordList3b = np.recarray(numCoords3b, coordinate)
    coordList4a = np.recarray(numCoords4a, coordinate)
    coordList4b = np.recarray(numCoords4b, coordinate)
    coordList4c = np.recarray(numCoords4c, coordinate)

    for i in range(numCoords3a):
        coordList3a[i].x = float(ptList3a[i][0])
        coordList3a[i].y = float(ptList3a[i][1])
    for i in range(numCoords3b):
        coordList3b[i].x = float(ptList3b[i][0])
        coordList3b[i].y = float(ptList3b[i][1])
    for i in range(numCoords4a):
        coordList4a[i].x = float(ptList4a[i][0])
        coordList4a[i].y = float(ptList4a[i][1])
    for i in range(numCoords4b):
        coordList4b[i].x = float(ptList4b[i][0])
        coordList4b[i].y = float(ptList4b[i][1])
    for i in range(numCoords4c):
        coordList4c[i].x = float(ptList4c[i][0])
        coordList4c[i].y = float(ptList4c[i][1])

    return coordList3a, coordList3b, coordList4a, coordList4b, coordList4c


def getTurbAtrbtCs3YAML(file_name):
    '''Retreive boundary coordinates from the <.yaml> file'''
    # Read in the .yaml file
    with open(file_name, 'r') as f:
        ptList = yaml.safe_load(f)['boundaries']['IIIa']

    # (Convert from <list> to <coordinate> array)
    # Determine how many points we have for the boundary
    numCoords = len(ptList)
    # Initialize the point list array
    coordList = np.recarray(numCoords, coordinate)
    for i in range(numCoords):
        coordList[i].x = float(ptList[i][0])
        coordList[i].y = float(ptList[i][1])

    return coordList

#--- Code for making splined boundaries ---#
def findNewPtOnLine(pt0, pt1, dist):
    # Given (x0,y0) and (x1,y1), finds (x2,y2) a distance dist from (x0,y0)
    # along line defined by (x0,y0) and (x1,y1).
    # https://math.stackexchange.com/questions/175896/finding-a-point-along-a-line-a-certain-distance-away-from-another-point
    newPt = np.recarray(1, coordinate)
    distTot = abs(coordDist(pt0, pt1))
    t = dist/distTot
    newPt.x = ((1-t)*pt0.x) + t*pt1.x
    newPt.y = ((1-t)*pt0.y) + t*pt1.y

    return newPt


def sliceBoundary(totCoordList, numGridLines):
    # Given a set of <coordinate> on a line (or boundary), and number of grid lines,
    # This will return a set of pts that have sliced that boundary line <numGridLines> many times.
    # TERMINOLOGY: 'Segment' slice of boundary line, 'Leg' means portion of boundary we're on
    tol = 1e-6  # Tolerance for reaching the end of the line
    # If we have 5 grid lines, that gives us 4 sectors (or divisions)
    numDivs = numGridLines-1
    # Initialize slice list (extra spot for starting point)
    segCoordList = np.recarray(numGridLines, coordinate)
    rsArcLen = getArcLength(totCoordList)    # Get total edge length
    # The length of each subdivided segment.
    rsSegmentLen = rsArcLen/numDivs

    # Traverse along the edge, marking where a segment ends
    distNeeded = rsSegmentLen  # Distance remaining till next marker
    distRemain = distNeeded   # Distance remaining until segment ends
    segCoordList[0] = totCoordList[0]  # Don't forget the first point.
    cntrLeg = 0               # Start at the first leg
    #-- Traverse and place --#
    leftPt = totCoordList[0]
    rightPt = totCoordList[1]
    distRemLeg = abs(coordDist(leftPt, rightPt))
    # Loop through all portions, marking as we go
    for cntrSeg in range(numDivs):
        # If the remainder of our segment is smaller than we need
        while(distRemLeg < distRemain):
            if (abs(distRemain - distRemLeg) > tol):
                distRemain = distRemain - distRemLeg    # Take out that much distance
                cntrLeg = cntrLeg + 1                   # Move to the next leg
                leftPt = totCoordList[cntrLeg]          # Move our left point
                rightPt = totCoordList[cntrLeg+1]
                distRemLeg = abs(coordDist(leftPt, rightPt))
            else:                                       # If rounding error makes us go past our line
                break

        segCoordList[cntrSeg+1] = findNewPtOnLine(leftPt, rightPt, distRemain)
        leftPt = segCoordList[cntrSeg+1]
        distRemLeg = distRemLeg - distRemain       # Take out how much we used
        distRemain = distNeeded                    # Reset how much we need

    return segCoordList


def coordDist(pt0, pt1):
    # Returns the euclidean distance between two <coordinate> points
    xDiff = pt0.x - pt1.x
    yDiff = pt0.y - pt1.y
    return np.sqrt(xDiff**2 + yDiff**2)


def getArcLength(coordList):
    # Returns the total distance of a given <np.ndarray> of <coordinate> type
    numCoordPairs = len(coordList)-1
    totDist = 0                   # Initialize to zero
    for i in range(numCoordPairs):  # Go through all the point pairs
        totDist = totDist + coordDist(coordList[i], coordList[i+1])

    return totDist


def makeCs3BndrySplines(vertexList, clsdBP, numGridLines):
    #-- Spline the boundary --#
    numSides = len(vertexList) - 1      # The number of sides for our original coordinate system. Usually (4) to Euclidean, but could be any number)
    splineList = np.empty(numSides, interp1d)                  # Init. array IOT save the Splines for each "side"
    buf = np.zeros((numSides, numGridLines, 2))                # Used to initalize the recarray to zeros
    segCoordList = np.recarray([numSides, numGridLines], dtype=coordinate, buf=buf)

    #- Create the splines for each side (<numSides> many)-#
    for i in range(numSides):
        BndPts = clsdBP[vertexList[i]:(vertexList[i+1]+1)]       # Extract the points for the "edge" we want
        segCoordList[i] = sliceBoundary(BndPts, numGridLines)    # Reparameterize the boundry to be defined by <numGridLines> many points
        splineList[i] = interp1d(segCoordList[i].x, segCoordList[i].y, kind='linear')   # Make the spline using NumPy's <interp1d>

    return splineList, segCoordList

class getPltClrs(object):
    # Made into a MATLAB function 02.Dec.18, converted to Python 26.Feb.20
    # For easy and pretty color plotting
    def getColor(self, argument):
        """Dispatch method"""
        method_name = 'color_' + str(argument)
        # Get the method from 'self'. Default to a lambda.
        method = getattr(self, method_name, lambda: "Invalid month")
        # Call the method as we return it
        return method()

    def color_1(self):
        return [0.6350, 0.0780, 0.1840]  # Red

    def color_2(self):
        return [0.9290, 0.6940, 0.1250]  # Yellow

    def color_3(self):
        return [0.4940, 0.1840, 0.5560]  # Purple

    def color_4(self):
        return [0.4660, 0.6740, 0.1880]  # Green

    def color_5(self):
        return [0, 0.4470, 0.7410]  # Blue

    def color_6(self):
        return [0.8500, 0.3250, 0.0980]  # Orange

    def color_7(self):
        return [0.7500, 0.7500, 0.0000]  # Puke yellow

    def color_8(self):
        return [0.0000, 0.4078, 0.3412]  # loyolagreen

    def color_9(self):
        return [1.0000, 0.8000, 1.0000]  # Pink

    def color_10(self):
        return [0.7843, 0.7843, 0.7843]  # loyolagray

    def color_11(self):
        return [0.6000, 0.4000, 0.2000]  # Brown

    def color_12(self):
        return [0.3010, 0.7450, 0.9330]  # SkyBlue
#--- Code for visualizing farm area ---#
def closeBndryList(bndryPts):
    # Appends the first element to the end of an <np.ndarray> of type <coordinate> for closed boundary #
    # Determine how many points we have for the boundary
    numCoords = len(bndryPts)
    # Initialize the point list array
    coordList = np.recarray((numCoords+1), coordinate)
    for i in range(numCoords):
        coordList[i].x = float(bndryPts[i].x)
        coordList[i].y = float(bndryPts[i].y)

    coordList[i+1].x = bndryPts[0].x
    coordList[i+1].y = bndryPts[0].y

    return coordList


def printBoundary(bndryPts, size):
    #-- Print the windfarm boundary. bndryPts must be <np.ndarray> of type <coordinate>
    plt.plot(bndryPts.x, bndryPts.y)
    plt.axis('scaled')                      # Trim the white space
    plt.axis('off')                         # Turn off the framing


def printBoundaryClr(bndryPts, colorNum):
    #-- Print the windfarm boundary with the passed Color (a number). bndryPts must be <np.ndarray> of type <coordinate>
    plt.plot(bndryPts.x, bndryPts.y, color=getPltClrs().getColor(colorNum))
    #plt.xlim(coordList.x.min(), coordList.x.max()) # scales the x-axis to only include the boundary
    plt.axis('scaled')                      # Trim the white space
    plt.axis('off')                         # Turn off the framing


def printBoundaryArray(bndryPtsX, bndryPtsY, colorNum):
    #-- Print the windfarm boundary. bndryPts must be <np.ndarray> of type <coordinate>
    plt.plot(bndryPtsX, bndryPtsY, color=getPltClrs().getColor(colorNum))
    plt.axis('scaled')                      # Trim the white space
    plt.axis('off')                         # Turn off the framing


def printVerticies(coordList, vertList, colorName):
    plt.hold = True
    plt.plot(coordList[vertList].x,
             coordList[vertList].y, 'o', color=colorName)


def printTurbines(coordList, colorName, turbRadius, bShowIndx=False):
    plt.hold = True
    plt.scatter(coordList.x, coordList.y, s=turbRadius, color=colorName)
    if bShowIndx:
        for i in range(len(coordList)):
            plt.text(coordList[i].x, coordList[i].y, str(i))

#-- Code for optimization of turbine locaitons --#
def makeCoordArray(turb_coords):
    # Takes coordinates in form turb_coords.x and .y and puts them into a
    # single array. For optimizer to use.
    x0 = np.concatenate((turb_coords.x, turb_coords.y))
    return x0


def makeCoordStruct(x0):
    # Takes coordinates in a line and puts them into the form turb_coords.x and .y
    # For optimzer use.
    nNumRtrs = int(len(x0)/2)

    coordList = np.recarray(nNumRtrs, coordinate)
    coordList.x = x0[0:nNumRtrs]
    coordList.y = x0[nNumRtrs:len(x0)]

    return coordList


def makeCoordMatrix(x0):
    # Makes an Mx2 matrix where [0,1] = [x,y]
    # For scipy.spatial.distance.pdist() function
    nNumRtrs = int(len(x0)/2)
    coordMat = x0.reshape((nNumRtrs, 2))
    return coordMat


def makeFirstCoordStruct(turb_coords):
    # Takes ripped .yaml coordinates and puts them into our struct format.
    # Only needs to be done once at the beginning.
    nNumRtrs = len(turb_coords)
    coordList = np.recarray(nNumRtrs, coordinate)

    coordList.x = turb_coords[:, 0]
    coordList.y = turb_coords[:, 1]
    # for i in range(nNumRtrs):
    #     coordList[i].x = turb_coords[i,0]
    #     coordList[i].y = turb_coords[i,1]

    return coordList


def checkTurbSpacing(x0, turb_diam, scaledTC):
    x0 = x0 * scaledTC                          # Scale things to normal
    testCoordMat = makeCoordMatrix(x0)           # make [[x1,y1],[x2,y2],...]

    cTurbSpace = ssd.pdist(testCoordMat, metric='euclidean') # Get the distance between each turbine
    constraints = cTurbSpace - (2*turb_diam)                 # Constrain that the turbines are less than 2 diams apart
    return constraints  # Negative if ok, positive if too close


def optimoStripArgTuples(args):
    # Takes the passed array and strips items into their proper variables.
    cntr = 0
    wind_dir_freq_len = int(args[0])
    cntr = cntr + 1
    wind_dir_freq = args[cntr:(wind_dir_freq_len + cntr)]
    cntr = cntr + wind_dir_freq_len
    wind_speeds_len = int(args[cntr])
    cntr = cntr + 1
    wind_speeds = args[cntr:(wind_speeds_len + cntr)]
    cntr = cntr + wind_speeds_len
    wind_speed_prob_len = int(args[cntr])
    cntr = cntr + 1
    wind_speed_prob_wid = int(args[cntr])
    cntr = cntr + 1
    wind_speed_prob_size = wind_speed_prob_len * wind_speed_prob_wid
    wind_speed_probs = args[cntr:(wind_speed_prob_size + cntr)]
    wind_speed_probs = wind_speed_probs.reshape(
        wind_speed_prob_len, wind_speed_prob_wid)
    cntr = cntr + wind_speed_prob_size
    wind_dir_len = int(args[cntr])
    cntr = cntr + 1
    wind_dir = args[cntr:(wind_dir_len + cntr)]
    cntr = cntr + wind_dir_len
    turb_diam = float(args[cntr])
    cntr = cntr + 1
    turb_ci = float(args[cntr])
    cntr = cntr + 1
    turb_co = float(args[cntr])
    cntr = cntr + 1
    rated_ws = float(args[cntr])
    cntr = cntr + 1
    rated_pwr = float(args[cntr])
    cntr = cntr + 1
    scaledAEP = float(args[cntr])
    cntr = cntr + 1
    scaledTC = float(args[cntr])

    return [wind_dir_freq, wind_speeds, wind_speed_probs, wind_dir,
            turb_diam, turb_ci, turb_co, rated_ws, rated_pwr, scaledAEP, scaledTC]


def optimoMakeArgTuples(wind_dir_freq, wind_speeds, wind_speed_probs, wind_dir, turb_diam, turb_ci, turb_co, rated_ws, rated_pwr, scaledAEP, scaledTC):
    # Takes the list of passed variables and concatenates them into one long array with size markers for matricies
    wind_speed_probs_size = len(wind_speed_probs) * len(wind_speed_probs[0])
    argLen = len(wind_dir_freq) \
        + len(wind_speeds) \
        + wind_speed_probs_size \
        + len(wind_dir) \
        + 4 \
        + 8  # 4 For lengths of first four entries
    # 7 For single element items <turb_diam, turb_ci, turb_co, rated_ws, rated_pwr, scaledAEP, scaledTurbCoords>

    args = np.zeros(argLen)
    cntr = 0  # Where we are right now.

    args[0] = len(wind_dir_freq)
    cntr = cntr + 1
    args[cntr:(len(wind_dir_freq)+cntr)] = wind_dir_freq
    cntr = cntr + len(wind_dir_freq)
    args[cntr] = len(wind_speeds)
    cntr = cntr + 1
    args[cntr:len(wind_speeds)+cntr] = wind_speeds
    cntr = cntr + len(wind_speeds)
    args[cntr] = len(wind_speed_probs)
    cntr = cntr + 1
    args[cntr] = len(wind_speed_probs[0])
    cntr = cntr + 1
    args[cntr:wind_speed_probs_size +
         cntr] = np.asarray(wind_speed_probs).reshape(-1)
    cntr = cntr + wind_speed_probs_size
    args[cntr] = len(wind_dir)
    cntr = cntr + 1
    args[cntr:len(wind_dir)+cntr] = wind_dir
    cntr = cntr + len(wind_dir)
    args[cntr] = turb_diam
    cntr = cntr + 1
    args[cntr] = turb_ci
    cntr = cntr + 1
    args[cntr] = turb_co
    cntr = cntr + 1
    args[cntr] = rated_ws
    cntr = cntr + 1
    args[cntr] = rated_pwr
    cntr = cntr + 1
    args[cntr] = scaledAEP
    cntr = cntr + 1
    args[cntr] = scaledTC

    return args

#-- Specific for the optimizaiton --#
def optimoFun(x0, args):
    # Rip and parse the data we need
    [wind_freq, wind_speeds, wind_speed_probs, wind_dir, turb_diam,
        turb_ci, turb_co, rated_ws, rated_pwr, scaledAEP, scaledTC] = optimoStripArgTuples(args)
    newCoords = makeCoordMatrix(x0)

    # Calculate the AEP, remembering to scale the coordinates
    dirAEP = iea37aepC.calcAEPcs3((newCoords * scaledTC), wind_freq, wind_speeds, wind_speed_probs,
                        wind_dir, turb_diam, turb_ci, turb_co, rated_ws, rated_pwr)
    scaledAEP = dirAEP / scaledAEP
    return -np.sum(scaledAEP)
    #return np.sum(dirAEP)

#-- Makes random start locations for cs3 --#
def iea37cs3randomstarts(numTurbs, splineList, vertexList, bndryPts, turb_diam):
    #-- Initialize our array --#
    buf = np.zeros((numTurbs, 2))
    turbRandoList = np.recarray((numTurbs), dtype=coordinate, buf=buf)
    minTurbDist = 2*turb_diam

    #-- Get the x-values --#
    xmin = bndryPts[vertexList[2]].x   # Our minimum x-value
    xmax = bndryPts[vertexList[0]].x   # our maximum x-value
    for i in range(numTurbs):
        turbRandoList[i].x = np.random.uniform(xmin, xmax)

    #-- Get the y-values --#
    #- Determine the upper and lower splines to use for the given x -#
    # Fake for-loop here for proximity checking.
    i = 0
    while i < numTurbs:
        ymin, ymax = getUpDwnYvals(
            turbRandoList[i].x, splineList, vertexList, bndryPts)
        # Get a random number in our bounds
        turbRandoList[i].y = np.random.uniform(ymin, ymax)
        # Check it doesn't conflict with nearby turbines
        for j in range(i):  # Check only the ones we've place so far
            # If this turbine has a proximity conflict
            if (coordDist(turbRandoList[i], turbRandoList[j]) < minTurbDist):
                turbRandoList[i].x = np.random.uniform(
                    xmin, xmax)  # Give it a new x-val
                i = i-1  # Redo the y-val too
                break  # Stop checking for conflicts and redo the y-values
        i = i+1

    return turbRandoList

#-- Returns the max and min y-vals for a given x-val in the cs3 boundary --#
def getUpDwnYvals(xCoord, splineList, vertexList, bndryPts):
    # Given there are 4 splines (with 0&1 below, 2&3 above),
    # returns the indecies of splines the given x-coord falls between
    
    #-- Upper. If it's out of bounds
    if (xCoord < bndryPts[vertexList[2]].x):
        ymax = bndryPts[vertexList[2]].y # Give it the y-value of our leftmost point
    # If it's to the left of the right upper spline
    elif (xCoord < bndryPts[vertexList[3]].x):
        ymax = splineList[2](xCoord)  # Make it the left upper spline
    # If it's to the left of the rightmost point
    elif (xCoord < bndryPts[vertexList[0]].x):
        ymax = splineList[3](xCoord)  # Make it the left upper spline
    else:
        ymax = bndryPts[vertexList[0]].y # Give it the y-value of our rightmost point

    #-- Lower. If it's to the left of the right lower spline
    if (xCoord < bndryPts[vertexList[2]].x):
        ymin = bndryPts[vertexList[2]].y # Give it the y-value of our leftmost point
    elif (xCoord < bndryPts[vertexList[1]].x):
        ymin = splineList[1](xCoord) # Make it the left upper spline
    elif (xCoord < bndryPts[vertexList[0]].x):
        ymin = splineList[0](xCoord)
    else:
        ymin = bndryPts[vertexList[0]].y # Give it the y-value of our rightmost point
    
    return ymin,ymax

#-- Returns neg numbers for oud of mounds coordinates, positive if it's in bounds --#
def checkBndryCons(x0, splineList, vertexList, bndryPts, scaledTC):
    x0 = x0 * scaledTC                   # Scale things to normal
    turbList = makeCoordStruct(x0)
    numTurbs = int(len(turbList))

    # Check to make sure our poits are in
    bndryCons = np.zeros(numTurbs*4)   # four values (two x and two y) for every turbine
    xmin = bndryPts[vertexList[2]].x   # Our minimum x-value
    xmax = bndryPts[vertexList[0]].x   # our maximum x-value
    
    # For every turbine
    for i in range(numTurbs):
        #- Check x-vals
        bndryCons[4*i] = (xmax - turbList[i].x)   # Positive good, neg bad
        bndryCons[4*i+1] = (turbList[i].x - xmin) # pos good, neg bad
        
        #- Check y-vals
        ymin,ymax = getUpDwnYvals(turbList[i].x, splineList, vertexList, bndryPts)
        bndryCons[4*i+2] = (ymax - turbList[i].y)
        bndryCons[4*i+3] = (turbList[i].y - ymin)
            
    return bndryCons


if __name__ == "__main__":
    numTurbs = 25

    # #- Load the boundary -#
    fn = "iea37-boundary-cs3.yaml"
    bndryPts = getTurbAtrbtCs3YAML(fn)
    clsdBP = closeBndryList(bndryPts)   # Duplicate the 1st coord for a closed boundary
    # #- Load the turbine and windrose atributes -#
    # fname_turb = "iea37-10mw.yaml"
    # fname_wr = "iea37-windrose-cs3.yaml"
    # wind_dir, wind_dir_freq, wind_speeds, wind_speed_probs, num_speed_bins, min_speed, max_speed = iea37aepC.getWindRoseYAML(
    #     fname_wr)
    # turb_ci, turb_co, rated_ws, rated_pwr, turb_diam = iea37aepC.getTurbAtrbtYAML(
    #     fname_turb)

    # #- Some display variables -#
    # displaySize = np.recarray(1, coordinate)
    # displaySize.x = 5
    # displaySize.y = 5
    # numLinspace = 10
    # numGridLines = 10                   # How many gridlines we'll use for the visualization
    # vertexList = [0, 6, 8, 9, 18]       # Hard code the vertices (though this could be done algorithmically)
    # numSides = len(vertexList) - 1
    # scaledAEP = 1e5
    # scaledTC = 1e3
    # #- args in the correct format for optimization -#
    # Args = optimoMakeArgTuples(wind_dir_freq, wind_speeds, wind_speed_probs,
    #                            wind_dir, turb_diam, turb_ci, turb_co, rated_ws, rated_pwr, scaledAEP, scaledTC)

    # # Spline up the boundary
    # [splineList, segCoordList] = makeCs3BndrySplines(vertexList, clsdBP, numGridLines)

    # #-- Use the example layout --#
    fn = "iea37-ex-opt3.yaml"
    turb_coords, fname_turb, fname_wr = iea37aepC.getTurbLocYAML(fn)
    x0s = makeFirstCoordStruct(turb_coords)
    # x0s = makeCoordStruct(x0a)
    x0a = makeCoordArray(x0s)
    # # printTurbines(x0s, getPltClrs().getColor(1), turb_diam/2)
    # # startAEP = optimoFun(x0a, Args)
    # numRestarts = 2                     # Number of restarts we're doing
    # listAEP = np.zeros(numRestarts)     # An array holding our AEP values
    # listTurbLocs = np.zeros((numRestarts, (numTurbs*2)))
    # bestResult = np.zeros(2)            # Index, AEP number

#     for cntr in range(numRestarts):
#         #-- Make some random starting turbine places --#
#         # turbRandoList = iea37cs3randomstarts(
#         #     numTurbs, splineList, vertexList, bndryPts, turb_diam)
#         #- Get our turbine list ready for processing -#
#         x0 = makeCoordArray(x0s)/scaledTC         # Get a random turbine placement and scale it
#         # startAEP = optimoFun(x0, Args)
#         # print(startAEP)

#         cons = ({'type': 'ineq', 'fun': lambda x:  checkBndryCons(x, splineList, vertexList, bndryPts, scaledTC)}, {
#                 'type': 'ineq', 'fun': lambda x: checkTurbSpacing(x, turb_diam, scaledTC)})
#         res = optimize.minimize(optimoFun, x0, args=Args, method='SLSQP',
#                                 constraints=cons, options={'disp': True, 'maxiter': 1000})
# #tol= 1e-6
#         #-- Save our results --#
#         listAEP[cntr] = optimoFun(res.x, Args)
#         listTurbLocs[cntr] = res.x

#     for j in range(numRestarts):
#         if (bestResult[1] > listAEP[j]):  # If our new AEP is better (Remember negative switches)
#             bestResult[1] = listAEP[j]    # Save it
#             bestResult[0] = j             # And the index of which run we're on

#     listTurbLocs = listTurbLocs * scaledTC
#     print("Best AEP:")
#     print(listAEP[int(bestResult[0])])  # Print the best one, have to make sure the index is an (int)
#    print(optimoFun(x0a, Args))
#     # save to csv file
#     np.savetxt('turblocs-10run-ex.csv', listTurbLocs[int(bestResult[0])], delimiter=',') # Save the best setup

    # for i in range(numSides):
    #     plt.hold = True
    #     printBoundaryArray(segCoordList[i].x, splineList[i](
    #         segCoordList[i].x), 5)

    # plt.axis('scaled')                      # Trim the white space
    # plt.axis('off')                         # Turn off the framing
    # plt.show()