import { http } from '@kit.NetworkKit';
import { util } from '@kit.ArkTS';
import { StreamPayload } from '../models/Types';
import { SseEvent, SseParser } from './SseParser';

export class ApiClient {
  baseUrl: string = '';
  token: string = '';
  private active: http.HttpRequest | undefined = undefined;

  async request<T>(path: string, method: http.RequestMethod = http.RequestMethod.GET,
    body: string = ''): Promise<T> {
    const request: http.HttpRequest = http.createHttp();
    try {
      const response: http.HttpResponse = await request.request(this.baseUrl + path, {
        method: method,
        header: { 'Authorization': 'Bearer ' + this.token, 'Content-Type': 'application/json' },
        extraData: body,
        expectDataType: http.HttpDataType.STRING,
        usingCache: false,
        connectTimeout: 10000,
        readTimeout: 30000
      });
      if (response.responseCode < 200 || response.responseCode >= 300) {
        throw new Error(response.responseCode === 401 ? '连接口令无效' :
          response.responseCode === 409 ? '内容已变化，请刷新后重试' : '请求失败，请检查服务连接');
      }
      return JSON.parse(response.result as string) as T;
    } finally {
      request.destroy();
    }
  }

  cancel(): void {
    if (this.active) {
      this.active.destroy();
      this.active = undefined;
    }
  }

  async chat(conversationId: string, content: string, clientId: string,
    onEvent: (event: string, payload: StreamPayload) => void): Promise<void> {
    this.cancel();
    const request: http.HttpRequest = http.createHttp();
    this.active = request;
    const decoder: util.TextDecoder = util.TextDecoder.create('utf-8', { fatal: false });
    let completed: boolean = false;
    let streamError: string = '';
    const parser: SseParser = new SseParser((event: SseEvent): void => {
      const payload: StreamPayload = JSON.parse(event.data) as StreamPayload;
      if (event.event === 'completed') {
        completed = true;
      }
      if (event.event === 'error') {
        streamError = payload.message ? payload.message : '回复中断，请重试';
      }
      onEvent(event.event, payload);
    });
    request.on('dataReceive', (chunk: ArrayBuffer): void => {
      try {
        parser.feed(decoder.decodeToString(new Uint8Array(chunk), { stream: true }));
      } catch (_) {
        streamError = '回复解析失败，请重试';
      }
    });
    try {
      const code: number = await request.requestInStream(this.baseUrl +
        '/v1/conversations/' + conversationId + '/messages', {
        method: http.RequestMethod.POST,
        header: { 'Authorization': 'Bearer ' + this.token, 'Content-Type': 'application/json',
          'Accept': 'text/event-stream' },
        extraData: JSON.stringify({ content: content, client_id: clientId, remember: true }),
        usingCache: false,
        connectTimeout: 10000,
        readTimeout: 120000
      });
      parser.feed(decoder.decodeToString(new Uint8Array(0), { stream: false }));
      if (code !== 200) {
        throw new Error(code === 409 ? '该消息已提交，请刷新后继续' : '连接失败，请检查口令和服务地址');
      }
      if (streamError || !completed) {
        throw new Error(streamError || '连接已断开，回复尚未完成');
      }
    } finally {
      if (this.active === request) {
        this.active = undefined;
        request.destroy();
      }
    }
  }
}
