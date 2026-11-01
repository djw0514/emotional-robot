export interface SseEvent {
  event: string;
  data: string;
}

// Pure string framing; UTF-8 decoding is performed incrementally by ApiClient.
export class SseParser {
  private buffer: string = '';
  private eventName: string = 'message';
  private dataLines: string[] = [];
  private onEvent: (event: SseEvent) => void;

  constructor(onEvent: (event: SseEvent) => void) {
    this.onEvent = onEvent;
  }

  feed(text: string): void {
    this.buffer += text;
    if (this.buffer.length > 1048576) {
      throw new Error('回复过长，请重新连接');
    }
    let newline: number = this.buffer.indexOf('\n');
    while (newline >= 0) {
      let line: string = this.buffer.substring(0, newline);
      this.buffer = this.buffer.substring(newline + 1);
      if (line.endsWith('\r')) {
        line = line.substring(0, line.length - 1);
      }
      if (line.length === 0) {
        if (this.dataLines.length > 0) {
          this.onEvent({ event: this.eventName, data: this.dataLines.join('\n') });
        }
        this.eventName = 'message';
        this.dataLines = [];
      } else if (line.startsWith('event:')) {
        this.eventName = line.substring(6).trim();
      } else if (line.startsWith('data:')) {
        let value: string = line.substring(5);
        this.dataLines.push(value.startsWith(' ') ? value.substring(1) : value);
      }
      newline = this.buffer.indexOf('\n');
    }
  }
}
