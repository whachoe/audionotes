package com.cjpa.notes.di

import android.content.Context
import androidx.room.Room
import com.cjpa.notes.data.local.AppDatabase
import com.cjpa.notes.data.local.NotesDao
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object DatabaseModule {

    @Provides
    @Singleton
    fun provideAppDatabase(@ApplicationContext context: Context): AppDatabase =
        Room.databaseBuilder(context, AppDatabase::class.java, "notes.db").build()

    @Provides
    @Singleton
    fun provideNotesDao(database: AppDatabase): NotesDao = database.notesDao()
}
