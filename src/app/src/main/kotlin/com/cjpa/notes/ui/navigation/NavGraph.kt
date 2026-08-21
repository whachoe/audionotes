package com.cjpa.notes.ui.navigation

import androidx.compose.runtime.Composable
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.cjpa.notes.ui.detail.NoteDetailScreen
import com.cjpa.notes.ui.notes.NotesListScreen
import com.cjpa.notes.ui.settings.SettingsScreen

sealed class Screen(val route: String) {
    data object NotesList : Screen("notes_list")
    data object Settings : Screen("settings")
    data object NoteDetail : Screen("note_detail/{noteId}") {
        fun createRoute(noteId: String) = "note_detail/$noteId"
    }
}

@Composable
fun NotesNavGraph(navController: NavHostController = rememberNavController()) {
    NavHost(navController = navController, startDestination = Screen.NotesList.route) {
        composable(Screen.NotesList.route) {
            NotesListScreen(
                onNoteClick = { localId -> navController.navigate(Screen.NoteDetail.createRoute(localId)) },
                onSettingsClick = { navController.navigate(Screen.Settings.route) }
            )
        }
        composable(
            route = Screen.NoteDetail.route,
            arguments = listOf(navArgument("noteId") { type = NavType.StringType })
        ) {
            NoteDetailScreen(onBack = { navController.popBackStack() })
        }
        composable(Screen.Settings.route) {
            SettingsScreen(onBack = { navController.popBackStack() })
        }
    }
}
