package com.example.cockpit.db

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import android.util.Log
import com.example.cockpit.model.TimeSeriesPoint

object SensorDatabaseHelper {
    private const val TAG = "SensorDatabaseHelper"
    private const val TABLE_POINTS = "points"
    private const val COL_TIMESTAMP = "timestamp"
    private const val COL_VALUE = "value"
    private const val COL_RAW_DELTA = "raw_delta"
    private const val COL_IS_REFERENCE = "is_reference"

    private fun getSafeDatabaseName(host: String, typeSid: Long, sensorId: Long): String {
        val safeHost = host.replace(Regex("[^a-zA-Z0-9_]"), "_")
        return "history_${safeHost}_${typeSid}_${sensorId}.db"
    }

    private class DatabaseHelper(context: Context, dbName: String) : 
        SQLiteOpenHelper(context, dbName, null, 1) {
        
        override fun onCreate(db: SQLiteDatabase) {
            db.execSQL(
                "CREATE TABLE $TABLE_POINTS (" +
                        "$COL_TIMESTAMP INTEGER PRIMARY KEY, " +
                        "$COL_VALUE REAL, " +
                        "$COL_RAW_DELTA REAL, " +
                        "$COL_IS_REFERENCE INTEGER" +
                        ")"
            )
        }

        override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
            db.execSQL("DROP TABLE IF EXISTS $TABLE_POINTS")
            onCreate(db)
        }
    }

    @Synchronized
    fun savePoints(context: Context, host: String, typeSid: Long, sensorId: Long, points: List<TimeSeriesPoint>) {
        if (points.isEmpty()) return
        val dbName = getSafeDatabaseName(host, typeSid, sensorId)
        val helper = DatabaseHelper(context, dbName)
        var db: SQLiteDatabase? = null
        try {
            db = helper.writableDatabase
            db.beginTransaction()
            
            // Prune data older than 3 days
            val threeDaysAgo = System.currentTimeMillis() - 3L * 24 * 3600 * 1000
            db.delete(TABLE_POINTS, "$COL_TIMESTAMP < ?", arrayOf(threeDaysAgo.toString()))

            for (point in points) {
                if (point.timestamp >= threeDaysAgo) {
                    val values = ContentValues().apply {
                        put(COL_TIMESTAMP, point.timestamp)
                        put(COL_VALUE, point.value)
                        put(COL_RAW_DELTA, point.rawDelta)
                        put(COL_IS_REFERENCE, if (point.isReference) 1 else 0)
                    }
                    db.insertWithOnConflict(TABLE_POINTS, null, values, SQLiteDatabase.CONFLICT_REPLACE)
                }
            }
            db.setTransactionSuccessful()
        } catch (e: Exception) {
            Log.e(TAG, "Error saving points for database $dbName", e)
        } finally {
            try {
                db?.endTransaction()
            } catch (e: Exception) {
                // ignore
            }
            try {
                db?.close()
            } catch (e: Exception) {
                // ignore
            }
            helper.close()
        }
    }

    @Synchronized
    fun loadPoints(context: Context, host: String, typeSid: Long, sensorId: Long): List<TimeSeriesPoint> {
        val dbName = getSafeDatabaseName(host, typeSid, sensorId)
        val helper = DatabaseHelper(context, dbName)
        val points = mutableListOf<TimeSeriesPoint>()
        var db: SQLiteDatabase? = null
        var cursor: android.database.Cursor? = null
        try {
            db = helper.readableDatabase
            
            // Prune old data on query (and load only points >= 3 days)
            val threeDaysAgo = System.currentTimeMillis() - 3L * 24 * 3600 * 1000
            
            cursor = db.query(
                TABLE_POINTS,
                arrayOf(COL_TIMESTAMP, COL_VALUE, COL_RAW_DELTA, COL_IS_REFERENCE),
                "$COL_TIMESTAMP >= ?",
                arrayOf(threeDaysAgo.toString()),
                null, null,
                "$COL_TIMESTAMP ASC"
            )

            while (cursor.moveToNext()) {
                val timestamp = cursor.getLong(0)
                val value = cursor.getDouble(1)
                val rawDelta = cursor.getDouble(2)
                val isReference = cursor.getInt(3) == 1
                points.add(TimeSeriesPoint(timestamp, value, rawDelta, isReference))
            }
        } catch (e: Exception) {
            Log.e(TAG, "Error loading points for database $dbName", e)
        } finally {
            cursor?.close()
            try {
                db?.close()
            } catch (e: Exception) {
                // ignore
            }
            helper.close()
        }
        return points
    }
}
