package com.cjpa.notes.data.remote

import com.cjpa.notes.data.repository.SettingsRepository
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.Interceptor
import okhttp3.Response
import javax.inject.Inject

/**
 * Retrofit/OkHttp is built once against a fixed placeholder base URL
 * ("https://placeholder.invalid/") so it never needs to be rebuilt when the
 * user edits Settings. This interceptor rewrites the scheme, host and port of
 * every outgoing request to the base URL the user entered, and prefixes the
 * request path with whatever path segment (if any) that base URL itself has -
 * e.g. base URL "https://host.example.com/reverse-proxy-prefix" + Retrofit
 * path "api/notes" resolves to "https://host.example.com/reverse-proxy-prefix/api/notes".
 */
class BaseUrlInterceptor @Inject constructor(
    private val settingsRepository: SettingsRepository
) : Interceptor {

    override fun intercept(chain: Interceptor.Chain): Response {
        val original = chain.request()
        val storedBaseUrl = settingsRepository.getBaseUrl()
        if (storedBaseUrl.isNullOrBlank()) {
            return chain.proceed(original)
        }
        val userUrl = storedBaseUrl.toHttpUrlOrNull() ?: return chain.proceed(original)

        val newUrl = original.url.newBuilder()
            .scheme(userUrl.scheme)
            .host(userUrl.host)
            .port(userUrl.port)
            .encodedPath(joinPaths(userUrl.encodedPath, original.url.encodedPath))
            .build()

        val newRequest = original.newBuilder().url(newUrl).build()
        return chain.proceed(newRequest)
    }
}
