using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Reflection;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;

internal static class PockPockChromeNativeHost
{
    private const int MaxMessageBytes = 65536;
    private const int GatewayTimeoutMilliseconds = 30000;
    private const string GatewayUrl = "http://127.0.0.1:8766";
    private static readonly UTF8Encoding StrictUtf8 = new UTF8Encoding(false, true);

    private static int Main(string[] args)
    {
        string pairingId = null;
        string internalToken = null;
        int connectedTabId = -1;
        string connectedOrigin = null;
        CancellationTokenSource pollCancellation = null;
        Stream output = null;
        object outputLock = new object();
        try
        {
            string extensionId = LoadExtensionId();
            if (args.Length != 1 ||
                !String.Equals(args[0], "chrome-extension://" + extensionId + "/", StringComparison.Ordinal))
            {
                Console.Error.WriteLine("Native Messaging caller is not the registered extension.");
                return 2;
            }

            var serializer = new JavaScriptSerializer();
            serializer.MaxJsonLength = MaxMessageBytes;
            Stream input = Console.OpenStandardInput();
            output = Console.OpenStandardOutput();
            bool connected = false;

            while (true)
            {
                byte[] body;
                if (!TryReadMessage(input, out body))
                {
                    return 0;
                }

                object parsed = serializer.DeserializeObject(StrictUtf8.GetString(body));
                var request = parsed as Dictionary<string, object>;
                if (request == null)
                {
                    WriteMessageSafe(output, serializer, outputLock, Error("invalid_message"));
                    continue;
                }

                object typeValue;
                if (!request.TryGetValue("type", out typeValue) || !(typeValue is string))
                {
                    WriteMessageSafe(output, serializer, outputLock, Error("invalid_message"));
                    continue;
                }

                string type = (string)typeValue;
                if (type == "connect")
                {
                    object tabIdValue;
                    object originValue;
                    int tabId;
                    string origin;
                    if (connected ||
                        request.Count != 3 ||
                        !request.TryGetValue("tabId", out tabIdValue) ||
                        !(tabIdValue is int) ||
                        (tabId = (int)tabIdValue) < 0 ||
                        !request.TryGetValue("origin", out originValue) ||
                        !(originValue is string) ||
                        !IsHttpOrigin((string)originValue))
                    {
                        WriteMessageSafe(
                            output,
                            serializer,
                            outputLock,
                            Error(connected ? "already_connected" : "invalid_scope")
                        );
                        continue;
                    }

                    origin = (string)originValue;
                    internalToken = LoadInternalToken();
                    Dictionary<string, object> relayPairing = GatewayRequest(
                        "POST",
                        "/api/internal/chrome-companion/host/connect",
                        new Dictionary<string, object>
                        {
                            { "extension_id", extensionId },
                            { "tab_id", tabId },
                            { "origin", origin }
                        },
                        internalToken,
                        5000
                    );
                    object pairingValue;
                    if (!relayPairing.TryGetValue("pairing_id", out pairingValue) ||
                        !(pairingValue is string) ||
                        !IsHexId((string)pairingValue))
                    {
                        WriteMessageSafe(output, serializer, outputLock, Error("relay_unavailable"));
                        return 3;
                    }

                    pairingId = (string)pairingValue;
                    connected = true;
                    connectedTabId = tabId;
                    connectedOrigin = origin;
                    WriteMessageSafe(output, serializer, outputLock, new Dictionary<string, object>
                    {
                        { "type", "connected" },
                        { "tabId", connectedTabId },
                        { "origin", connectedOrigin },
                        { "pairingId", pairingId }
                    });
                    pollCancellation = new CancellationTokenSource();
                    string activePairingId = pairingId;
                    string activeToken = internalToken;
                    int activeTabId = connectedTabId;
                    string activeOrigin = connectedOrigin;
                    CancellationToken cancellationToken = pollCancellation.Token;
                    Task.Run(() => PollRelay(
                        activePairingId,
                        activeTabId,
                        activeOrigin,
                        activeToken,
                        output,
                        serializer,
                        outputLock,
                        cancellationToken
                    ));
                    continue;
                }

                if (type == "result" && connected)
                {
                    object resultPairingValue;
                    object requestIdValue;
                    object tabIdValue;
                    object originValue;
                    object resultValue;
                    if (request.Count != 6 ||
                        !request.TryGetValue("pairingId", out resultPairingValue) ||
                        !(resultPairingValue is string) ||
                        !String.Equals((string)resultPairingValue, pairingId, StringComparison.Ordinal) ||
                        !request.TryGetValue("requestId", out requestIdValue) ||
                        !(requestIdValue is string) ||
                        !IsHexId((string)requestIdValue) ||
                        !request.TryGetValue("tabId", out tabIdValue) ||
                        !(tabIdValue is int) ||
                        (int)tabIdValue != connectedTabId ||
                        !request.TryGetValue("origin", out originValue) ||
                        !(originValue is string) ||
                        !String.Equals((string)originValue, connectedOrigin, StringComparison.Ordinal) ||
                        !request.TryGetValue("result", out resultValue) ||
                        !(resultValue is Dictionary<string, object>))
                    {
                        WriteMessageSafe(output, serializer, outputLock, Error("invalid_result"));
                        continue;
                    }

                    GatewayRequest(
                        "POST",
                        "/api/internal/chrome-companion/host/result",
                        new Dictionary<string, object>
                        {
                            { "pairing_id", pairingId },
                            { "request_id", (string)requestIdValue },
                            { "tab_id", connectedTabId },
                            { "origin", connectedOrigin },
                            { "result", resultValue }
                        },
                        internalToken,
                        5000
                    );
                    continue;
                }

                if (type == "disconnect" && request.Count == 1)
                {
                    WriteMessageSafe(output, serializer, outputLock, new Dictionary<string, object>
                    {
                        { "type", "disconnected" }
                    });
                    return 0;
                }

                WriteMessageSafe(output, serializer, outputLock, Error("unsupported_message"));
            }
        }
        catch (Exception)
        {
            Console.Error.WriteLine("Native Messaging protocol failed.");
            return 1;
        }
        finally
        {
            if (pollCancellation != null)
            {
                pollCancellation.Cancel();
            }
            if (pairingId != null && internalToken != null)
            {
                try
                {
                    GatewayRequest(
                        "POST",
                        "/api/internal/chrome-companion/host/disconnect",
                        new Dictionary<string, object> { { "pairing_id", pairingId } },
                        internalToken,
                        2000
                    );
                }
                catch (Exception)
                {
                    Console.Error.WriteLine("Could not clear the local Chrome pairing.");
                }
            }
        }
    }

    private static void PollRelay(
        string pairingId,
        int tabId,
        string origin,
        string token,
        Stream output,
        JavaScriptSerializer serializer,
        object outputLock,
        CancellationToken cancellationToken)
    {
        int failures = 0;
        while (!cancellationToken.IsCancellationRequested)
        {
            try
            {
                string path = "/api/internal/chrome-companion/host/next?pairing_id=" +
                    Uri.EscapeDataString(pairingId);
                Dictionary<string, object> response = GatewayRequest(
                    "GET",
                    path,
                    null,
                    token,
                    GatewayTimeoutMilliseconds
                );
                failures = 0;
                object commandValue;
                if (!response.TryGetValue("command", out commandValue) || commandValue == null)
                {
                    continue;
                }

                var command = commandValue as Dictionary<string, object>;
                object commandPairing;
                object commandRequest;
                object commandTab;
                object commandOrigin;
                object commandRun;
                object commandOperation;
                object commandPayload;
                if (command == null ||
                    !command.TryGetValue("pairing_id", out commandPairing) ||
                    !(commandPairing is string) ||
                    !String.Equals((string)commandPairing, pairingId, StringComparison.Ordinal) ||
                    !command.TryGetValue("request_id", out commandRequest) ||
                    !(commandRequest is string) ||
                    !IsHexId((string)commandRequest) ||
                    !command.TryGetValue("tab_id", out commandTab) ||
                    !(commandTab is int) ||
                    (int)commandTab != tabId ||
                    !command.TryGetValue("origin", out commandOrigin) ||
                    !(commandOrigin is string) ||
                    !String.Equals((string)commandOrigin, origin, StringComparison.Ordinal) ||
                    !command.TryGetValue("run_id", out commandRun) ||
                    !(commandRun is string) ||
                    !IsHexId((string)commandRun) ||
                    !command.TryGetValue("operation", out commandOperation) ||
                    !(commandOperation is string) ||
                    !command.TryGetValue("payload", out commandPayload) ||
                    !(commandPayload is Dictionary<string, object>))
                {
                    Console.Error.WriteLine("The local Chrome relay returned an invalid command.");
                    WriteMessageSafe(output, serializer, outputLock, Error("invalid_relay_command"));
                    return;
                }

                WriteMessageSafe(output, serializer, outputLock, new Dictionary<string, object>
                {
                    { "type", "command" },
                    { "pairingId", pairingId },
                    { "requestId", (string)commandRequest },
                    { "runId", (string)commandRun },
                    { "tabId", tabId },
                    { "origin", origin },
                    { "operation", (string)commandOperation },
                    { "payload", commandPayload }
                });
            }
            catch (GatewayStatusException error)
            {
                if (error.StatusCode == 404 || error.StatusCode == 410 || error.StatusCode == 401)
                {
                    WriteMessageSafe(output, serializer, outputLock, Error("relay_disconnected"));
                    return;
                }
                failures++;
                Console.Error.WriteLine("The local Chrome relay returned an HTTP error.");
            }
            catch (Exception)
            {
                failures++;
                Console.Error.WriteLine("The local Chrome relay could not be reached.");
            }

            if (failures >= 3)
            {
                WriteMessageSafe(output, serializer, outputLock, Error("relay_unavailable"));
                return;
            }
            if (cancellationToken.WaitHandle.WaitOne(500))
            {
                return;
            }
        }
    }

    private static Dictionary<string, object> GatewayRequest(
        string method,
        string path,
        object body,
        string token,
        int timeoutMilliseconds)
    {
        var request = (HttpWebRequest)WebRequest.Create(GatewayUrl + path);
        request.Method = method;
        request.Proxy = null;
        request.AllowAutoRedirect = false;
        request.Timeout = timeoutMilliseconds;
        request.ReadWriteTimeout = timeoutMilliseconds;
        request.Headers["X-PockPock-Internal-Token"] = token;
        if (body != null)
        {
            byte[] bodyBytes = StrictUtf8.GetBytes(new JavaScriptSerializer().Serialize(body));
            if (bodyBytes.Length > MaxMessageBytes)
            {
                throw new InvalidDataException("The Chrome relay request exceeds the message limit.");
            }
            request.ContentType = "application/json; charset=utf-8";
            request.ContentLength = bodyBytes.Length;
            using (Stream requestStream = request.GetRequestStream())
            {
                requestStream.Write(bodyBytes, 0, bodyBytes.Length);
            }
        }

        try
        {
            using (var response = (HttpWebResponse)request.GetResponse())
            using (Stream responseStream = response.GetResponseStream())
            {
                byte[] responseBytes = ReadBounded(responseStream, MaxMessageBytes);
                if (responseBytes.Length == 0)
                {
                    return new Dictionary<string, object>();
                }
                var serializer = new JavaScriptSerializer();
                serializer.MaxJsonLength = MaxMessageBytes;
                var result = serializer.DeserializeObject(StrictUtf8.GetString(responseBytes))
                    as Dictionary<string, object>;
                if (result == null)
                {
                    throw new InvalidDataException("The local Chrome relay returned invalid JSON.");
                }
                return result;
            }
        }
        catch (WebException error)
        {
            var response = error.Response as HttpWebResponse;
            int statusCode = response == null ? 0 : (int)response.StatusCode;
            if (response != null)
            {
                response.Close();
            }
            throw new GatewayStatusException(statusCode);
        }
    }

    private static byte[] ReadBounded(Stream stream, int maximumBytes)
    {
        using (var buffer = new MemoryStream())
        {
            byte[] chunk = new byte[4096];
            int read;
            while ((read = stream.Read(chunk, 0, chunk.Length)) > 0)
            {
                if (buffer.Length + read > maximumBytes)
                {
                    throw new InvalidDataException("The local Chrome relay response exceeds the message limit.");
                }
                buffer.Write(chunk, 0, read);
            }
            return buffer.ToArray();
        }
    }

    private static void WriteMessageSafe(
        Stream output,
        JavaScriptSerializer serializer,
        object outputLock,
        object message)
    {
        lock (outputLock)
        {
            WriteMessage(output, serializer, message);
        }
    }

    private static string LoadInternalToken()
    {
        string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        if (String.IsNullOrEmpty(localAppData))
        {
            throw new InvalidDataException("The local application data directory is unavailable.");
        }
        string tokenPath = Path.Combine(localAppData, "FrogAI", "services.token");
        string token = File.ReadAllText(tokenPath, StrictUtf8).Trim();
        if (String.IsNullOrEmpty(token))
        {
            throw new InvalidDataException("The local service token is unavailable.");
        }
        return token;
    }

    private static bool IsHexId(string value)
    {
        if (value == null || value.Length != 32)
        {
            return false;
        }
        foreach (char character in value)
        {
            if (!((character >= '0' && character <= '9') || (character >= 'a' && character <= 'f')))
            {
                return false;
            }
        }
        return true;
    }

    private sealed class GatewayStatusException : Exception
    {
        public readonly int StatusCode;
        public GatewayStatusException(int statusCode)
        {
            StatusCode = statusCode;
        }
    }

    private static string LoadExtensionId()
    {
        string hostDirectory = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
        string idPath = Path.Combine(hostDirectory, "extension-id.txt");
        string id = File.ReadAllText(idPath, StrictUtf8).Trim();
        if (id.Length != 32)
        {
            throw new InvalidDataException("Invalid extension ID configuration.");
        }
        foreach (char character in id)
        {
            if (character < 'a' || character > 'p')
            {
                throw new InvalidDataException("Invalid extension ID configuration.");
            }
        }
        return id;
    }

    private static bool IsHttpOrigin(string value)
    {
        Uri uri;
        if (!Uri.TryCreate(value, UriKind.Absolute, out uri) ||
            (uri.Scheme != Uri.UriSchemeHttp && uri.Scheme != Uri.UriSchemeHttps) ||
            String.IsNullOrEmpty(uri.Host) ||
            !String.IsNullOrEmpty(uri.UserInfo) ||
            uri.AbsolutePath != "/" ||
            !String.IsNullOrEmpty(uri.Query) ||
            !String.IsNullOrEmpty(uri.Fragment))
        {
            return false;
        }
        return String.Equals(value, uri.GetLeftPart(UriPartial.Authority), StringComparison.Ordinal);
    }

    private static Dictionary<string, object> Error(string code)
    {
        return new Dictionary<string, object>
        {
            { "type", "error" },
            { "code", code }
        };
    }

    private static bool TryReadMessage(Stream input, out byte[] body)
    {
        byte[] header = new byte[4];
        int first = input.ReadByte();
        if (first < 0)
        {
            body = null;
            return false;
        }
        header[0] = (byte)first;
        ReadExactly(input, header, 1, 3);

        uint length = (uint)header[0] |
                      ((uint)header[1] << 8) |
                      ((uint)header[2] << 16) |
                      ((uint)header[3] << 24);
        if (length == 0 || length > MaxMessageBytes)
        {
            throw new InvalidDataException("Invalid Native Messaging frame length.");
        }

        body = new byte[(int)length];
        ReadExactly(input, body, 0, body.Length);
        return true;
    }

    private static void ReadExactly(Stream stream, byte[] buffer, int offset, int count)
    {
        while (count > 0)
        {
            int read = stream.Read(buffer, offset, count);
            if (read <= 0)
            {
                throw new EndOfStreamException("Truncated Native Messaging frame.");
            }
            offset += read;
            count -= read;
        }
    }

    private static void WriteMessage(Stream output, JavaScriptSerializer serializer, object message)
    {
        byte[] body = StrictUtf8.GetBytes(serializer.Serialize(message));
        if (body.Length == 0 || body.Length > MaxMessageBytes)
        {
            throw new InvalidDataException("Native Messaging response exceeds the limit.");
        }

        uint length = (uint)body.Length;
        byte[] header = new byte[]
        {
            (byte)(length & 0xff),
            (byte)((length >> 8) & 0xff),
            (byte)((length >> 16) & 0xff),
            (byte)((length >> 24) & 0xff)
        };
        output.Write(header, 0, header.Length);
        output.Write(body, 0, body.Length);
        output.Flush();
    }
}
