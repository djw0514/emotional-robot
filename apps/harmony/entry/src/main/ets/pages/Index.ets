import { http } from '@kit.NetworkKit';
import { util } from '@kit.ArkTS';
import { common } from '@kit.AbilityKit';
import { preferences } from '@kit.ArkData';
import { ApiClient } from '../services/ApiClient';
import { ChatMessage, ConversationInfo, DeletionJob, MemoryDetail, MemoryEvidence,
  MemoryItem, MemoryList, MemoryVersion, SettingsResult, StreamPayload, UserInfo } from '../models/Types';

@Entry
@Component
struct Index {
  @State private tab: number = 2;
  @State private endpoint: string = '';
  @State private connectionToken: string = '';
  @State private connected: boolean = false;
  @State private busy: boolean = false;
  @State private working: boolean = false;
  @State private memoryEnabled: boolean = true;
  @State private modeLabel: string = '';
  @State private notice: string = '';
  @State private input: string = '';
  @State private messages: ChatMessage[] = [];
  @State private memories: MemoryItem[] = [];
  @State private conversations: ConversationInfo[] = [];
  @State private showHistory: boolean = false;
  @State private detailId: string = '';
  @State private detailContent: string = '';
  @State private detailRevision: number = 0;
  @State private detailStatus: string = '';
  @State private versions: MemoryVersion[] = [];
  @State private evidence: MemoryEvidence[] = [];
  @State private newMemory: string = '';
  private api: ApiClient = new ApiClient();
  private conversationId: string = '';
  private generation: number = 0;
  private connectionRevision: number = 0;
  private memoryLoad: number = 0;
  private detailLoad: number = 0;

  aboutToAppear(): void {
    this.loadEndpoint().catch((error: Error) => { this.error(error); });
  }

  aboutToDisappear(): void {
    this.generation++;
    this.api.cancel();
  }

  private async loadEndpoint(): Promise<void> {
    const context = this.getUIContext().getHostContext() as common.UIAbilityContext;
    const store = await preferences.getPreferences(context, { name: 'connection' });
    this.endpoint = await store.get('endpoint', '') as string;
  }

  private error(error: Error): void {
    this.notice = error.message || '操作失败，请稍后重试';
  }

  private async connect(): Promise<void> {
    this.working = true;
    this.connectionRevision++;
    this.generation++;
    this.api.cancel();
    this.busy = false;
    this.connected = false;
    this.messages = [];
    this.memories = [];
    this.conversations = [];
    this.detailId = '';
    this.detailContent = '';
    this.versions = [];
    this.evidence = [];
    this.conversationId = '';
    try {
      const endpoint: string = this.endpoint.trim().replace(/\/+$/, '');
      if (!/^https?:\/\/[^\s]+$/.test(endpoint) || !this.connectionToken.trim()) {
        throw new Error('请填写完整服务地址和连接口令');
      }
      if (endpoint.startsWith('http://') &&
        !/^http:\/\/(127\.0\.0\.1|localhost|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+)(:\d+)?$/.test(endpoint)) {
        throw new Error('公网服务请使用 HTTPS 地址');
      }
      this.api.baseUrl = endpoint;
      this.api.token = this.connectionToken.trim();
      const info = await this.api.request<UserInfo>('/v1/me');
      this.memoryEnabled = info.memory_enabled;
      this.modeLabel = info.provider === 'demo' ? '演示模式' : 'DeepSeek 对话';
      this.conversations = await this.api.request<ConversationInfo[]>('/v1/conversations');
      if (this.conversations.length > 0) {
        this.conversationId = this.conversations[0].id;
      } else {
        const created = await this.api.request<ConversationInfo>('/v1/conversations', http.RequestMethod.POST, '{}');
        this.conversationId = created.id;
      }
      this.connected = true;
      await this.refreshMessages();
      await this.refreshMemories();
      const context = this.getUIContext().getHostContext() as common.UIAbilityContext;
      const store = await preferences.getPreferences(context, { name: 'connection' });
      await store.put('endpoint', endpoint);
      await store.flush();
      this.notice = '已连接。可以开始聊天了';
      this.tab = 0;
    } catch (error) {
      this.connected = false;
      this.api.token = '';
      this.messages = [];
      this.memories = [];
      this.error(error as Error);
    } finally {
      this.working = false;
    }
  }

  private async refreshMessages(): Promise<void> {
    if (this.conversationId) {
      const revision: number = this.connectionRevision;
      const id: string = this.conversationId;
      const rows = await this.api.request<ChatMessage[]>('/v1/conversations/' + id + '/messages');
      if (revision === this.connectionRevision && id === this.conversationId) { this.messages = rows; }
    }
  }

  private async refreshMemories(): Promise<void> {
    const revision: number = this.connectionRevision;
    const load: number = ++this.memoryLoad;
    const result = await this.api.request<MemoryList>('/v1/memories?status=all&limit=200');
    if (revision === this.connectionRevision && load === this.memoryLoad) { this.memories = result.items; }
  }

  private async openConversation(id: string): Promise<void> {
    this.conversationId = id;
    this.showHistory = false;
    try { await this.refreshMessages(); } catch (error) { this.error(error as Error); }
  }

  private async createConversation(): Promise<void> {
    try {
      const created = await this.api.request<ConversationInfo>('/v1/conversations', http.RequestMethod.POST,
        JSON.stringify({ title: new Date().toLocaleString() }));
      this.conversationId = created.id;
      this.messages = [];
      this.conversations = await this.api.request<ConversationInfo[]>('/v1/conversations');
      this.notice = '已开始新对话，长期记忆仍然保留';
    } catch (error) { this.error(error as Error); }
  }

  private async sendMessage(): Promise<void> {
    if (this.busy || !this.connected || !this.input.trim()) { return; }
    const text: string = this.input.trim();
    const requestId: string = util.generateRandomUUID();
    const assistantId: string = util.generateRandomUUID();
    const current: number = ++this.generation;
    this.input = '';
    this.busy = true;
    this.messages = [...this.messages, { id: requestId, role: 'user', content: text },
      { id: assistantId, role: 'assistant', content: '' }];
    let reply: string = '';
    try {
      await this.api.chat(this.conversationId, text, requestId, (event: string, payload: StreamPayload): void => {
        if (current !== this.generation) { return; }
        if (event === 'token' && payload.text) {
          reply += payload.text;
          this.messages = this.messages.map((message: ChatMessage): ChatMessage =>
            message.id === assistantId ? { id: assistantId, role: 'assistant', content: reply } : message);
        }
      });
      if (current === this.generation) {
        this.notice = '记忆会在后台整理，可稍后到记忆页刷新查看';
      }
    } catch (error) {
      if (current === this.generation) { this.error(error as Error); }
    } finally {
      if (current === this.generation) { this.busy = false; }
    }
  }

  private async setMemoryEnabled(value: boolean): Promise<void> {
    try {
      const result = await this.api.request<SettingsResult>('/v1/memory-settings', http.RequestMethod.PATCH,
        JSON.stringify({ memory_enabled: value }));
      this.memoryEnabled = result.memory_enabled;
      this.notice = value ? '已开启新记忆整理' : '已暂停产生新记忆，聊天历史仍会保存';
    } catch (error) { this.error(error as Error); }
  }

  private async selectMemory(id: string): Promise<void> {
    const revision: number = this.connectionRevision;
    const load: number = ++this.detailLoad;
    try {
      const detail = await this.api.request<MemoryDetail>('/v1/memories/' + id);
      if (revision !== this.connectionRevision || load !== this.detailLoad) { return; }
      this.detailId = detail.id;
      this.detailContent = detail.content;
      this.detailRevision = detail.revision;
      this.detailStatus = detail.status;
      this.versions = detail.versions;
      this.evidence = detail.evidence;
    } catch (error) { this.error(error as Error); }
  }

  private async saveMemory(confirm: boolean = false): Promise<void> {
    this.working = true;
    try {
      if (confirm) {
        await this.api.request<MemoryItem>('/v1/memories/' + this.detailId, http.RequestMethod.PATCH,
          JSON.stringify({ revision: this.detailRevision, content: this.detailContent, status: 'active', reason: 'confirmation' }));
      } else {
        await this.api.request<MemoryItem>('/v1/memories/' + this.detailId, http.RequestMethod.PATCH,
          JSON.stringify({ revision: this.detailRevision, content: this.detailContent, reason: 'correction' }));
      }
      await this.selectMemory(this.detailId);
      await this.refreshMemories();
      this.notice = '记忆已更新';
    } catch (error) { this.error(error as Error); } finally { this.working = false; }
  }

  private async addMemory(): Promise<void> {
    if (!this.newMemory.trim()) { return; }
    this.working = true;
    try {
      await this.api.request<MemoryItem>('/v1/memories', http.RequestMethod.POST,
        JSON.stringify({ content: this.newMemory.trim() }));
      this.newMemory = '';
      await this.refreshMemories();
      this.notice = '已记住';
    } catch (error) { this.error(error as Error); } finally { this.working = false; }
  }

  private async deleteMemory(): Promise<void> {
    const targetId: string = this.detailId;
    const result = await this.getUIContext().getPromptAction().showDialog({
      title: '忘记这条记忆？',
      message: '会清除关联来源、同一来源产生的记忆及已有助手回复，防止再次记起。',
      buttons: [{ text: '取消', color: '#50685E' }, { text: '忘记', color: '#AE534D' }]
    });
    if (result.index !== 1) { return; }
    this.working = true;
    try {
      let job = await this.api.request<DeletionJob>('/v1/memories/' + targetId, http.RequestMethod.DELETE);
      this.detailLoad++;
      this.detailId = '';
      this.detailContent = '';
      this.evidence = [];
      this.versions = [];
      await this.refreshMemories();
      await this.refreshMessages();
      for (let attempt: number = 0; attempt < 10 && (job.status === 'pending' || job.status === 'running'); attempt++) {
        await new Promise<void>((resolve) => { setTimeout(resolve, 500); });
        job = await this.api.request<DeletionJob>('/v1/deletion-jobs/' + job.id);
      }
      this.notice = job.status === 'completed' ? '已停止使用，并清理在线存储中的关联内容' : '已停止使用，后台仍在清理';
    } catch (error) { this.error(error as Error); } finally { this.working = false; }
  }

  @Builder
  private chatPage() {
    Column({ space: 12 }) {
      Row({ space: 8 }) {
        Text('慢慢说，我在听').fontSize(18).layoutWeight(1)
        Button('会话').onClick(() => { this.showHistory = !this.showHistory; }).enabled(this.connected && !this.busy)
        Button('新对话').onClick(() => { this.createConversation(); }).enabled(this.connected && !this.busy)
      }.width('100%')
      if (this.showHistory) {
        List({ space: 4 }) {
          ForEach(this.conversations, (item: ConversationInfo) => {
            ListItem() { Text(item.title).padding(12).onClick(() => { this.openConversation(item.id); }) }
          }, (item: ConversationInfo) => item.id)
        }.height(150)
      }
      List({ space: 12 }) {
        if (this.messages.length === 0) {
          ListItem() {
            Text(this.connected ? '从今天的一件小事开始吧。' : '先到设置页连接你的服务。').fontColor('#768078').padding(24)
          }
        }
        ForEach(this.messages, (message: ChatMessage) => {
          ListItem() {
            Column({ space: 6 }) {
              Text(message.role === 'user' ? '你' : '心伴').fontSize(12).fontColor('#768078')
              Text(message.content || '正在想…').fontSize(17).lineHeight(26).textSelection(TextSelectableMode.SELECTABLE)
            }.alignItems(HorizontalAlign.Start).padding(16).width('100%')
            .backgroundColor(message.role === 'user' ? '#E5EEE7' : '#FFFFFF').borderRadius(18)
          }
        }, (message: ChatMessage) => message.id)
      }.layoutWeight(1).width('100%')
      Row({ space: 8 }) {
        TextInput({ placeholder: '说点什么…', text: this.input }).layoutWeight(1).onChange((value: string) => { this.input = value; })
        if (this.busy) {
          Button('停止').onClick(() => { this.generation++; this.api.cancel(); this.busy = false; this.notice = '已停止回复'; })
        } else {
          Button('发送').backgroundColor('#50685E').onClick(() => { this.sendMessage(); }).enabled(this.connected && this.input.trim().length > 0)
        }
      }
    }.height('100%').padding(16)
  }

  @Builder
  private memoryPage() {
    Scroll() {
      Column({ space: 12 }) {
        Row() {
          Column({ space: 4 }) {
            Text('值得记住的事').fontSize(22).fontWeight(FontWeight.Medium)
            Text('你可以查看、纠正，也可以让它忘记').fontSize(12).fontColor('#768078')
          }.alignItems(HorizontalAlign.Start).layoutWeight(1)
          Button('刷新').onClick(() => { this.refreshMemories().catch((error: Error) => { this.error(error); }); }).enabled(this.connected)
        }.width('100%')
        Row() {
          Text('整理新记忆').layoutWeight(1)
          Toggle({ type: ToggleType.Switch, isOn: this.memoryEnabled }).enabled(this.connected && !this.busy)
            .onChange((value: boolean) => { this.setMemoryEnabled(value); })
        }.padding(12).backgroundColor('#FFFFFF').borderRadius(12)
        TextArea({ placeholder: '手动记下一件事', text: this.newMemory }).height(80).maxLength(2000)
          .onChange((value: string) => { this.newMemory = value; })
        Button('添加记忆').enabled(this.connected && !this.working && !this.busy).onClick(() => { this.addMemory(); })
        if (this.detailId) {
          Column({ space: 10 }) {
            Text('记忆详情 · 第 ' + this.detailRevision + ' 版').fontSize(18)
            TextArea({ text: this.detailContent }).height(100).maxLength(2000).onChange((value: string) => { this.detailContent = value; })
            Row({ space: 8 }) {
              Button('保存纠正').onClick(() => { this.saveMemory(); }).enabled(!this.working && !this.busy && this.detailStatus !== 'superseded')
              if (this.detailStatus === 'candidate') {
                Button('确认记住').onClick(() => { this.saveMemory(true); }).enabled(!this.working && !this.busy)
              }
              Button('忘记').fontColor('#AE534D').backgroundColor('#F9EAE7').onClick(() => { this.deleteMemory(); }).enabled(!this.working && !this.busy)
            }
            Text('来源').fontWeight(FontWeight.Medium)
            if (this.evidence.length === 0) { Text('由你手动添加').fontColor('#768078') }
            ForEach(this.evidence, (item: MemoryEvidence) => { Text(item.content).fontSize(14) }, (item: MemoryEvidence) => item.id)
            Text('修改记录').fontWeight(FontWeight.Medium)
            ForEach(this.versions, (item: MemoryVersion) => {
              Text('第 ' + item.revision + ' 版：' + item.content).fontSize(14).fontColor('#768078')
            }, (item: MemoryVersion) => item.revision.toString())
            Button('收起').onClick(() => { this.detailId = ''; this.detailContent = ''; this.evidence = []; this.versions = []; })
          }.padding(16).width('100%').backgroundColor('#FFFFFF').borderRadius(16).alignItems(HorizontalAlign.Start)
        }
        if (this.memories.length === 0) { Text('还没有记忆。聊聊你的称呼和偏好，或手动添加。').fontColor('#768078').padding(20) }
        ForEach(this.memories, (item: MemoryItem) => {
          Column({ space: 8 }) {
            Text(item.status === 'candidate' ? '待你确认' : item.status === 'superseded' ? '已被新记忆替代' : '已记住').fontSize(12).fontColor('#768078')
            Text(item.content).fontSize(16)
          }.alignItems(HorizontalAlign.Start).padding(16).width('100%').backgroundColor('#FFFFFF').borderRadius(16)
          .onClick(() => { this.selectMemory(item.id); })
        }, (item: MemoryItem) => item.id)
      }.padding(16).width('100%').alignItems(HorizontalAlign.Start)
    }.height('100%')
  }

  @Builder
  private settingsPage() {
    Column({ space: 18 }) {
      Text('连接你的心伴').fontSize(26).fontWeight(FontWeight.Medium)
      Text('对话和记忆保存在你连接的服务中。').fontColor('#768078')
      TextInput({ placeholder: '服务地址，例如 https://你的域名', text: this.endpoint }).onChange((value: string) => { this.endpoint = value; })
      TextInput({ placeholder: '连接口令', text: this.connectionToken }).type(InputType.Password)
        .onChange((value: string) => { this.connectionToken = value; })
      Text('这里填写本应用的连接口令。DeepSeek API Key 只配置在服务端。口令仅在本次使用期间保留。').fontSize(13).fontColor('#768078')
      Button(this.working ? '正在连接…' : '连接').width('100%').backgroundColor('#50685E')
        .enabled(!this.working && !this.busy).onClick(() => { this.connect(); })
      if (this.connected) { Text('已连接 · ' + this.modeLabel).fontColor('#50685E') }
    }.padding(24).alignItems(HorizontalAlign.Start).width('100%')
  }

  build() {
    Column() {
      Row() {
        Text('心伴').fontSize(28).fontWeight(FontWeight.Bold).fontColor('#344D42').layoutWeight(1)
        Text(this.connected ? this.modeLabel : '尚未连接').fontSize(12).fontColor('#768078')
      }.padding({ left: 20, right: 20, top: 16, bottom: 12 }).width('100%')
      if (this.notice) { Text(this.notice).fontSize(12).fontColor('#50685E').padding(10).width('100%').backgroundColor('#EAF0E8') }
      Tabs({ index: this.tab }) {
        TabContent() { this.chatPage() }.tabBar('聊天')
        TabContent() { this.memoryPage() }.tabBar('记忆')
        TabContent() { this.settingsPage() }.tabBar('设置')
      }.barPosition(BarPosition.End).onChange((index: number) => { this.tab = index; }).layoutWeight(1)
    }.width('100%').height('100%').backgroundColor('#F7F5F0')
  }
}
