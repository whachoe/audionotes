package com.cjpa.notes.data.remote

import java.time.Instant
import java.time.LocalDateTime
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeParseException

/**
 * Best-effort ISO-8601 parser for the timestamp strings the backend sends
 * (created_at / updated_at). Tries the strict "Z"/offset forms first and
 * falls back to a zone-less local timestamp, finally to "now" so a single
 * malformed timestamp never crashes a list refresh.
 */
internal fun parseIsoInstantOrNow(value: String?): Long {
    if (value.isNullOrBlank()) return System.currentTimeMillis()
    return try {
        Instant.parse(value).toEpochMilli()
    } catch (e: DateTimeParseException) {
        try {
            OffsetDateTime.parse(value).toInstant().toEpochMilli()
        } catch (e2: DateTimeParseException) {
            try {
                LocalDateTime.parse(value).atZone(ZoneId.systemDefault()).toInstant().toEpochMilli()
            } catch (e3: DateTimeParseException) {
                System.currentTimeMillis()
            }
        }
    }
}

/**
 * Same best-effort parsing as [parseIsoInstantOrNow], but for an optional
 * field (scheduled_at) where most notes simply don't have a value - falling
 * back to "now" would be actively misleading here, so a null/unparseable
 * value stays null instead.
 */
internal fun parseIsoInstantOrNull(value: String?): Long? {
    if (value.isNullOrBlank()) return null
    return try {
        Instant.parse(value).toEpochMilli()
    } catch (e: DateTimeParseException) {
        try {
            OffsetDateTime.parse(value).toInstant().toEpochMilli()
        } catch (e2: DateTimeParseException) {
            try {
                LocalDateTime.parse(value).atZone(ZoneId.systemDefault()).toInstant().toEpochMilli()
            } catch (e3: DateTimeParseException) {
                null
            }
        }
    }
}
