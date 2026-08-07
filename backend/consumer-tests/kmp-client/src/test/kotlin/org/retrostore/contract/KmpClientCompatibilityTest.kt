package org.retrostore.contract

import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import kotlinx.coroutines.runBlocking
import okio.ByteString.Companion.toByteString
import org.junit.jupiter.api.Assertions.assertArrayEquals
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.retrostore.RetrostoreClient
import org.retrostore.client.common.proto.SystemState
import org.retrostore.client.common.proto.Trs80Model

class KmpClientCompatibilityTest {
    @Test
    fun currentKmpClientExercisesItsFiveCandidateMethods() = runBlocking {
        val http = HttpClient.newHttpClient()
        val candidateUrl = System.getProperty("candidateUrl")
        val client = RetrostoreClient("$candidateUrl/api/%s") { url, body ->
            val request =
                HttpRequest.newBuilder(URI.create(url))
                    .POST(HttpRequest.BodyPublishers.ofByteArray(body))
                    .build()
            val response = http.send(request, HttpResponse.BodyHandlers.ofByteArray())
            assertEquals(200, response.statusCode(), "HTTP status for $url")
            response.body()
        }

        val apps = client.fetchApps(0, 2)
        assertEquals(2, apps.size)
        assertEquals("Armored Patrol", apps.first().name)

        val fixture = client.getApp(FIXTURE_APP_ID)
        assertNotNull(fixture)
        assertEquals("Space Invaders (Model I Edition)", fixture?.name)

        val images = client.fetchMediaImages(FIXTURE_APP_ID)
        assertEquals(2, images.size)
        val command = images.single { it.filename == "command.CMD" }
        assertEquals(3_477, command.data_.size)

        val state =
            SystemState(
                model = Trs80Model.MODEL_I,
                registers = SystemState.Registers(pc = 0x2345),
                memoryRegions =
                    listOf(
                        SystemState.MemoryRegion(
                            start = 512,
                            length = 99,
                            data_ = byteArrayOf(5, 6, 7, 8).toByteString())))

        val token = client.uploadState(state)
        assertTrue(token > 0)

        val downloaded = client.downloadState(token)
        assertNotNull(downloaded)
        assertEquals(0x2345, downloaded?.registers?.pc)
        assertEquals(4, downloaded?.memoryRegions?.single()?.length)
        assertArrayEquals(byteArrayOf(5, 6, 7, 8), downloaded?.memoryRegions?.single()?.data_?.toByteArray())
    }

    private companion object {
        const val FIXTURE_APP_ID = "259847aa-ce3a-48bb-a037-e392beb96b22"
    }
}
