#!/bin/sh
colnum=$2
firstcol=$1
lastcol=$2
#echo "cut -d ' ' -f $firstcol-$lastcol $3"\
result=`cut -d ' ' -f $firstcol-$lastcol $3`
while [ "$result" != "" ]
do
    echo $result
    firstcol=$((firstcol+colnum))
    lastcol=$((lastcol+colnum))
    [ "`cut -d ' ' -f  $firstcol $3`" != "U*" ] && {
	    firstcol=$((firstcol-1))
    	    lastcol=$((lastcol-1))
    }
    result=`cut -d ' ' -f $firstcol-$lastcol $3`
    #echo "cut -d ' ' -f $firstcol-$lastcol $3"
done
