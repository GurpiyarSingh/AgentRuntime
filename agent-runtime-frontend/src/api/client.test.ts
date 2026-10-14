import { createFakeServer, TOOLS } from '../test/fakeServer';
import { ApiClient, ApiError } from './client';

function respond(status: number, body: unknown) {
  return () => Promise.resolve(new Response(JSON.stringify(body), { status }));
}

describe('ApiClient', () => {
  it('loads the tool list', async () => {
    const server = createFakeServer();
    const client = new ApiClient({ baseUrl: '', fetch: server.fetch });
    expect(await client.tools()).toEqual(TOOLS);
  });

  it('prefixes the base URL without doubling slashes', async () => {
    const server = createFakeServer();
    await new ApiClient({ baseUrl: 'https://agent.example.com/', fetch: server.fetch }).health();
    expect(server.requests[0]?.url).toBe('https://agent.example.com/health');
  });

  it('sends the current API key on every request', async () => {
    const server = createFakeServer();
    let key = 'first';
    const client = new ApiClient({ baseUrl: '', fetch: server.fetch, getApiKey: () => key });
    await client.health();
    key = 'second';
    await client.health();
    expect(server.requests.map((r) => r.headers.get('X-API-Key'))).toEqual(['first', 'second']);
  });

  it('omits the API key header when none is set', async () => {
    const server = createFakeServer();
    await new ApiClient({ baseUrl: '', fetch: server.fetch }).health();
    expect(server.requests[0]?.headers.has('X-API-Key')).toBe(false);
  });

  it("surfaces the server's detail message", async () => {
    const client = new ApiClient({ baseUrl: '', fetch: respond(400, { detail: 'Unknown model' }) });
    await expect(client.health()).rejects.toMatchObject({ status: 400, message: 'Unknown model' });
  });

  it('joins validation error messages', async () => {
    const detail = [{ msg: 'too long' }, { msg: 'bad pattern' }];
    const client = new ApiClient({ baseUrl: '', fetch: respond(422, { detail }) });
    await expect(client.health()).rejects.toThrow('too long; bad pattern');
  });

  it('reports an unreachable server as a network error', async () => {
    const client = new ApiClient({ baseUrl: '', fetch: createFakeServer({ offline: true }).fetch });
    const error = await client.health().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).isNetworkError).toBe(true);
  });

  it('streams chat events and skips unknown event types', async () => {
    const server = createFakeServer({
      chats: [
        [
          {
            type: 'model_token',
            data: { run_id: 'r', session_id: 's', model: 'm', step: 1, text: 'Hi' },
          },
          {
            type: 'final_answer',
            data: { run_id: 'r', session_id: 's', model: 'm', step: 1, content: 'Hi' },
          },
        ],
      ],
    });
    const client = new ApiClient({ baseUrl: '', fetch: server.fetch });

    const types: string[] = [];
    for await (const event of client.chatStream(
      { message: 'hello', model: 'gpt-4o' },
      new AbortController().signal,
    )) {
      types.push(event.type);
    }

    expect(types).toEqual(['model_token', 'final_answer']);
    expect(server.requests[0]?.body).toEqual({ message: 'hello', model: 'gpt-4o' });
  });

  it('URL-encodes each segment of a download path', async () => {
    const server = createFakeServer();
    await new ApiClient({ baseUrl: '', fetch: server.fetch }).downloadFile('my docs/a b#1.pdf');
    expect(server.requests[0]?.url).toBe('/v1/files/my%20docs/a%20b%231.pdf');
  });
});
