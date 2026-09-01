package com.cjpa.notes.ui.navigation

import androidx.compose.runtime.Composable
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import androidx.navigation.navDeepLink
import com.cjpa.notes.ui.detail.NoteDetailScreen
import com.cjpa.notes.ui.notes.NotesListScreen
import com.cjpa.notes.ui.settings.SettingsScreen

sealed class Screen(val route: String) {
    data object NotesList : Screen("notes_list")

    /**
     * `token` is optional: a plain in-app navigation ("settings", no query
     * string) leaves it absent, while the Google sign-in deep link
     * (copywastenotes://auth?token=...) supplies it - see SettingsViewModel,
     * which reads it from SavedStateHandle to complete the sign-in.
     */
    data object Settings : Screen("settings?token={token}") {
        const val NAV_ROUTE = "settings"
        const val DEEP_LINK_URI_PATTERN = "copywastenotes://auth?token={token}"
    }

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
                onSettingsClick = { navController.navigate(Screen.Settings.NAV_ROUTE) }
            )
        }
        composable(
            route = Screen.NoteDetail.route,
            arguments = listOf(navArgument("noteId") { type = NavType.StringType })
        ) {
            NoteDetailScreen(onBack = { navController.popBackStack() })
        }
        composable(
            route = Screen.Settings.route,
            arguments = listOf(
                navArgument("token") {
                    type = NavType.StringType
                    nullable = true
                    defaultValue = null
                }
            ),
            deepLinks = listOf(navDeepLink { uriPattern = Screen.Settings.DEEP_LINK_URI_PATTERN })
        ) {
            SettingsScreen(onBack = { navController.popBackStack() })
        }
    }
}
