package com.cjpa.notes.data.remote

import okhttp3.HttpUrl.Companion.toHttpUrlOrNull

/**
 * Resolves a server-relative path (e.g. "/api/notes/{id}/audio") against the
 * user's configured base URL, honoring any path prefix the base URL itself
 * carries (e.g. a reverse-proxy sub-path) - the same join Retrofit requests
 * get via [BaseUrlInterceptor], exposed here for non-Retrofit callers like the
 * in-app audio player.
 */
fun resolveServerUrl(baseUrl: String?, relativePath: String): String? {
    if (baseUrl.isNullOrBlank()) return null
    val base = baseUrl.toHttpUrlOrNull() ?: return null
    return base.newBuilder()
        .encodedPath(joinPaths(base.encodedPath, relativePath))
        .build()
        .toString()
}

internal fun joinPaths(prefix: String, path: String): String {
    val trimmedPrefix = prefix.trimEnd('/')
    return if (trimmedPrefix.isEmpty()) path else trimmedPrefix + path
}
