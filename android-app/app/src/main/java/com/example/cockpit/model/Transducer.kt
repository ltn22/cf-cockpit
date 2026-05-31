package com.example.cockpit.model

data class TimeSeriesPoint(
    val timestamp: Long,
    val value: Double,
    val rawDelta: Double,
    val isReference: Boolean
)

data class Transducer(
    val id: Long,
    val typeSid: Long,
    val unit: String,
    val precision: Int,
    val valueSid: Long = 100092L,
    val value: Double? = null,
    val isLoading: Boolean = false,
    val showStats: Boolean = false,
    val isStatsLoading: Boolean = false,
    val statistics: Map<String, Double>? = null, // min, max, mean, median, stdev, sampleCount
    val isObserving: Boolean = false,
    val timeSeries: List<TimeSeriesPoint> = emptyList()
) {
    val typeName: String
        get() = when (typeSid) {
            100001L -> "Air Temperature"
            100002L -> "Average Distance"
            100003L -> "Barometric Pressure"
            100004L -> "East Wind Speed"
            100005L -> "North Wind Speed"
            100006L -> "Precipitation"
            100007L -> "Relative Humidity"
            100008L -> "Solar Radiation"
            100009L -> "Strike Count"
            100010L -> "Tilt"
            100011L -> "Transducer Type"
            100012L -> "Vapor Pressure"
            100013L -> "Wind Direction"
            100014L -> "Wind Gust"
            100015L -> "Wind Speed"
            100016L -> "X Orientation"
            100017L -> "Y Orientation"
            else -> "Sensor-$typeSid"
        }
}
