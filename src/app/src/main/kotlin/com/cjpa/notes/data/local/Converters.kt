package com.cjpa.notes.data.local

import androidx.room.TypeConverter

class Converters {
    @TypeConverter
    fun uploadStateToString(state: UploadState): String = state.name

    @TypeConverter
    fun stringToUploadState(value: String): UploadState =
        UploadState.entries.firstOrNull { it.name == value } ?: UploadState.PENDING
}
