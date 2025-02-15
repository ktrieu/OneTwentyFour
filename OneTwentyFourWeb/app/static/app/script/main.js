function updateRidingWindow(id) {
    var idNumeric = id.substring(id.indexOf("_") + 1);
    var riding = ridings[idNumeric]
    $("#riding-name").text(riding["name"]);
    for (var key in riding["projected"]) {
        var selector = "#riding-result-" + key.toLowerCase();
        $(selector).text(riding["projected"][key].toFixed(2) + "%");
    }
    for (var key in riding["swings"]) {
        var selector = "#riding-swing-" + key.toLowerCase();
        $(selector).text(riding["swings"][key].toFixed(2) + "%");
    }
}

//yes, it's already in the CSS but I have no idea how to sync those up
colors = {
    'PC': "#2c338e",
    'LIB': "#ed1b36",
    'NDP': "#f48120",
    'OTH': "#98999b"
}

function colorRiding(idx) {
    var idNumeric = this.id.substring(this.id.indexOf("_") + 1);
    var winner = "";
    var resultMax = 0;
    var ridingData = ridings[idNumeric];
    for (var key in ridingData['projected']) {
        if (ridingData['projected'][key] > resultMax) {
            resultMax = ridingData['projected'][key];
            winner = key;
        }
    }
    $(this).css({ 'fill': colors[winner] });
    console.log(this.resultMax);
}

initPollGraph = function () {
    var graphConfig = {
        type: "line",
        data: {
            datasets: []
        },
        options: {
            scales: {
                xAxes: [{
                    type: 'time',
                    distribution: 'linear',
                    time: {
                        min: "2018-05-09",
                        max: "2018-06-07",
                        round: "day",
                    }
                }]
            },
            tooltips: {
                callbacks: {
                    label: function (tooltipItem, data) {
                        var label = data.datasets[tooltipItem.datasetIndex].label || '';

                        if (label) {
                            label += ': ';
                        }
                        label += tooltipItem.yLabel.toFixed(2);
                        return label;
                    }
                }
            }
        }
    }
    pollData = {};
    for (var i = 0; i < pastPolls.length; i++) {
        averagePoint = pastPolls[i];
        for (party in averagePoint.current) {
            if (!(party in pollData)) {
                pollData[party] = [];
            }
            pollData[party].push({ x: averagePoint.date, y: averagePoint.current[party] });
        }
    }
    for (party in pollData) {
        graphConfig.data.datasets.push({
            label: party,
            fill: false,
            backgroundColor: colors[party],
            borderColor: colors[party],
            data: pollData[party]
        })
    }
    var canvas = $("#poll_graph")[0];
    var ctx = canvas.getContext('2d');
    window.pollGraph = new Chart(ctx, graphConfig);
}

hexWithOpacity = function(hex, opacity) {
    var result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
    var r = parseInt(result[1], 16);
    var g = parseInt(result[2], 16);
    var b = parseInt(result[3], 16);
    return "rgba(" + r + ", " + g + ", " + b + ", " + opacity + ")";
}

initSeatGraph = function () {
    var graphConfig = {
        type: "line",
        data: {
            datasets: []
        },
        options: {
            scales: {
                xAxes: [{
                    type: "linear",
                    ticks: {
                        min: 0,
                        max: 127,
                    },
                    scaleLabel: {
                        display: true,
                        labelString: 'Seat Count'
                    }
                }],
                yAxes: [{
                    type: "linear",
                    scaleLabel: {
                        display: true,
                        labelString: 'Occurrences (out of 500 simulations)'
                    }
                }],
            },
        }
    }
    for (party in seatOutcomes) {
        var partySeatData = [];
        for (k in seatOutcomes[party]) {
            //skip outcomes with no seats
            if (k == 0) {
                continue;
            }
            partySeatData.push({ x: k, y: seatOutcomes[party][k] });
        }
        graphConfig.data.datasets.push({
            label: party,
            lineTension: 0.1,
            fill: true,
            backgroundColor: hexWithOpacity(colors[party], 0.3),
            borderColor: hexWithOpacity(colors[party], 0.3),
            data: partySeatData
        })
    }
    var canvas = $("#seat-graph")[0];
    var ctx = canvas.getContext('2d');
    window.pollGraph = new Chart(ctx, graphConfig);
}

$().ready(function () {
    svgNode = $("#riding-map")[0];
    //init svg-pan-zoom
    svgNode.addEventListener("load", function () {
        svgPanZoom("#riding-map", { maxZoom: 20 })
        //get the root svg node
        svgRoot = svgNode.contentDocument.documentElement;
        ridingShapes = $("polygon", svgRoot);
        ridingShapes.click(function (evt) {
            updateRidingWindow(evt.target.id);
        });
        ridingShapes.each(colorRiding);
    });
    initPollGraph();
    initSeatGraph();
})
