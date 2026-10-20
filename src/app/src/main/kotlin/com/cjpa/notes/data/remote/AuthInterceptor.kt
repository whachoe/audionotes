package com.cjpa.notes.data.remote

import com.cjpa.notes.data.repository.SettingsRepository
import okhttp3.Interceptor
import okhttp3.Response
import javax.inject.Inject

/** Adds the bearer token to every request except /api/health. */
class AuthInterceptor @Inject constructor(
    private val settingsRepository: SettingsRepository
) : Interceptor {

    override fun intercept(chain: Interceptor.Chain): Response {
        val original = chain.request()
        if (original.url.encodedPath.endsWith("/health")) {
            return chain.proceed(original)
        }
        val token = settingsRepository.getSessionToken()
        val request = if (!token.isNullOrBlank()) {
            original.newBuilder()
                .addHeader("Authorization", "Bearer $token")
                .build()
        } else {
            original
        }
        return chain.proceed(request)
    }
}
