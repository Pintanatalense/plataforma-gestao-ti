import { TestBed } from '@angular/core/testing';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';
import { of, throwError } from 'rxjs';
import { ChannelLinkInfo, NotificationsService } from '../../core/services/notifications.service';
import { NotificationsAdminService } from '../../core/services/notifications-admin.service';
import { MyChannelsComponent, minutesLeft } from './preferences/my-channels.component';
import { TelegramConfigComponent } from './admin/telegram-config.component';
import { WhatsAppConfigComponent, webhookUrl } from './admin/whatsapp-config.component';
import { SlackConfigComponent } from './admin/slack-config.component';

const TELEGRAM: ChannelLinkInfo = {
  channel: 'telegram', label: 'Telegram', available: true, bot_username: 'gti_bot', linked: false, linked_at: null
};

async function mount<T>(component: new () => T, providers: unknown[]) {
  await TestBed.configureTestingModule({
    imports: [component as never],
    providers: [provideAnimationsAsync(), ...(providers as never[])]
  }).compileComponents();
  const fixture = TestBed.createComponent(component);
  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
  return fixture;
}

describe('minutesLeft', () => {
  it('rounds up and never goes negative', () => {
    const now = Date.parse('2026-10-18T12:00:00Z');
    expect(minutesLeft('2026-10-18T12:10:00Z', now)).toBe(10);
    expect(minutesLeft('2026-10-18T12:00:30Z', now)).toBe(1);
    expect(minutesLeft('2026-10-18T11:00:00Z', now)).toBe(0);
  });
});

describe('MyChannelsComponent', () => {
  function service(over: Partial<ChannelLinkInfo> = {}, extra: object = {}) {
    return {
      myChannels: vi.fn().mockReturnValue(of({ channels: [{ ...TELEGRAM, ...over }] })),
      createLinkCode: vi.fn().mockReturnValue(
        of({ code: 'ABC234', expires_at: new Date(Date.now() + 9 * 60_000).toISOString(), command: '/vincular ABC234', deep_link: 'https://t.me/gti_bot?start=ABC234' })
      ),
      unlinkChannel: vi.fn().mockReturnValue(of(undefined)),
      ...extra
    };
  }
  const provide = (svc: object) => [{ provide: NotificationsService, useValue: svc }];

  it('explains when the channel is not enabled by the admin and offers no code', async () => {
    const fixture = await mount(MyChannelsComponent, provide(service({ available: false })));
    expect(fixture.nativeElement.textContent).toContain('ainda não foi habilitado');
    expect(fixture.nativeElement.querySelector('[data-testid="generate"]')).toBeNull();
  });

  it('generates a code and shows the command and the deep link', async () => {
    const svc = service();
    const fixture = await mount(MyChannelsComponent, provide(svc));
    (fixture.nativeElement.querySelector('[data-testid="generate"]') as HTMLElement).click();
    fixture.detectChanges();

    expect(svc.createLinkCode).toHaveBeenCalledWith('telegram');
    expect(fixture.nativeElement.querySelector('[data-testid="code-command"]').textContent).toBe('/vincular ABC234');
    const link = fixture.nativeElement.querySelector('[data-testid="code-box"] a') as HTMLAnchorElement;
    expect(link.href).toBe('https://t.me/gti_bot?start=ABC234');
    expect(link.rel).toContain('noopener');
    expect(fixture.nativeElement.textContent).toContain('@gti_bot');
  });

  it('shows the linked state with unlink, and unlink asks for confirmation', async () => {
    const svc = service({ linked: true, linked_at: '2026-10-18T12:00:00Z' });
    const fixture = await mount(MyChannelsComponent, provide(svc));
    expect(fixture.nativeElement.textContent).toContain('Vinculado');
    expect(fixture.nativeElement.querySelector('[data-testid="generate"]')).toBeNull();

    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);
    fixture.componentInstance.unlink(TELEGRAM);
    expect(svc.unlinkChannel).not.toHaveBeenCalled();

    confirmSpy.mockReturnValue(true);
    fixture.componentInstance.unlink(TELEGRAM);
    expect(svc.unlinkChannel).toHaveBeenCalledWith('telegram');
    confirmSpy.mockRestore();
  });

  it('shows the code only under the channel it was generated for', async () => {
    const slack: ChannelLinkInfo = { channel: 'slack', label: 'Slack', available: true, bot_username: null, bot_name: 'gti_bot', linked: false, linked_at: null };
    const svc = service({}, { myChannels: vi.fn().mockReturnValue(of({ channels: [TELEGRAM, slack] })) });
    const fixture = await mount(MyChannelsComponent, provide(svc));
    fixture.componentInstance.generate(slack);
    fixture.detectChanges();

    const boxes = fixture.nativeElement.querySelectorAll('[data-testid="code-box"]');
    expect(boxes.length).toBe(1);
    expect(fixture.nativeElement.querySelector('[data-testid="channel-slack"] [data-testid="code-box"]')).not.toBeNull();
    expect(fixture.nativeElement.querySelector('[data-testid="channel-telegram"] [data-testid="code-box"]')).toBeNull();
    expect(boxes[0].textContent).toContain('gti_bot');
  });

  it('shows the server message when the code cannot be generated', async () => {
    const err = { error: { error: { message: 'Muitos códigos gerados na última hora.' } } };
    const svc = service({}, { createLinkCode: vi.fn().mockReturnValue(throwError(() => err)) });
    const fixture = await mount(MyChannelsComponent, provide(svc));
    fixture.componentInstance.generate(TELEGRAM);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[role="alert"]').textContent).toContain('Muitos códigos');
  });
});

describe('TelegramConfigComponent', () => {
  const CONFIG = { enabled: false, bot_token: '', bot_username: null, app_base_url: '' };

  it('loads the config, never receives the real token and saves what the admin typed', async () => {
    const api = {
      getTelegramConfig: vi.fn().mockReturnValue(of({ ...CONFIG, bot_token: '********', bot_username: 'gti_bot' })),
      saveTelegramConfig: vi.fn().mockReturnValue(of({ ...CONFIG, enabled: true, bot_token: '********', bot_username: 'gti_bot' }))
    };
    const fixture = await mount(TelegramConfigComponent, [{ provide: NotificationsAdminService, useValue: api }]);
    expect(fixture.nativeElement.textContent).toContain('@gti_bot');
    const token = fixture.nativeElement.querySelector('[data-testid="tg-token"]') as HTMLInputElement;
    expect(token.type).toBe('password');

    const c = fixture.componentInstance;
    c.config.update((cfg) => ({ ...cfg!, enabled: true, bot_token: '123:NOVO', app_base_url: 'https://ti.x' }));
    c.save();
    expect(api.saveTelegramConfig).toHaveBeenCalledWith({ enabled: true, bot_token: '123:NOVO', app_base_url: 'https://ti.x' });
    expect(c.config()!.bot_token).toBe('********');
  });

  it('shows the API validation message (e.g. token refused) and keeps the form', async () => {
    const err = { error: { error: { message: 'O Telegram recusou o token: Unauthorized' } } };
    const api = {
      getTelegramConfig: vi.fn().mockReturnValue(of(CONFIG)),
      saveTelegramConfig: vi.fn().mockReturnValue(throwError(() => err))
    };
    const fixture = await mount(TelegramConfigComponent, [{ provide: NotificationsAdminService, useValue: api }]);
    fixture.componentInstance.save();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[role="alert"]').textContent).toContain('recusou o token');
    expect(fixture.componentInstance.saving()).toBe(false);
  });

  it('reports a load failure', async () => {
    const api = { getTelegramConfig: vi.fn().mockReturnValue(throwError(() => new Error('x'))) };
    const fixture = await mount(TelegramConfigComponent, [{ provide: NotificationsAdminService, useValue: api }]);
    expect(fixture.nativeElement.querySelector('[role="alert"]').textContent).toContain('Não foi possível carregar');
  });
});

describe('WhatsAppConfigComponent', () => {
  const CONFIG = {
    enabled: false, access_token: '', app_secret: '', phone_number_id: '', graph_version: 'v21.0', template_name: '',
    template_language: 'pt_BR', app_base_url: '', display_phone: null, verified_name: null,
    verify_token: 'tok-123', webhook_path: '/api/v1/integrations/whatsapp/webhook'
  };
  const provide = (api: object) => [{ provide: NotificationsAdminService, useValue: api }];

  it('builds the webhook URL from the current origin', () => {
    expect(webhookUrl('/api/v1/integrations/whatsapp/webhook', 'https://ti.x/')).toBe('https://ti.x/api/v1/integrations/whatsapp/webhook');
  });

  it('shows what to register at Meta (callback URL, verify token, signed field)', async () => {
    const api = { getWhatsAppConfig: vi.fn().mockReturnValue(of(CONFIG)) };
    const fixture = await mount(WhatsAppConfigComponent, provide(api));
    const box = fixture.nativeElement.querySelector('[data-testid="wa-webhook"]').textContent;
    expect(box).toContain('/api/v1/integrations/whatsapp/webhook');
    expect(box).toContain('tok-123');
    expect(box).toContain('messages');
  });

  it('keeps secrets as password fields and sends what the admin typed, trimmed', async () => {
    const api = {
      getWhatsAppConfig: vi.fn().mockReturnValue(of({ ...CONFIG, access_token: '********', app_secret: '********' })),
      saveWhatsAppConfig: vi.fn().mockReturnValue(of({ ...CONFIG, enabled: true, access_token: '********', app_secret: '********' }))
    };
    const fixture = await mount(WhatsAppConfigComponent, provide(api));
    expect((fixture.nativeElement.querySelector('[data-testid="wa-token"]') as HTMLInputElement).type).toBe('password');
    expect((fixture.nativeElement.querySelector('[data-testid="wa-secret"]') as HTMLInputElement).type).toBe('password');

    const c = fixture.componentInstance;
    c.config.update((cfg) => ({ ...cfg!, enabled: true, phone_number_id: ' 1055 ', template_name: ' aviso_ti ' }));
    c.save();
    expect(api.saveWhatsAppConfig).toHaveBeenCalledWith({
      enabled: true, access_token: '********', app_secret: '********', phone_number_id: '1055', graph_version: 'v21.0',
      template_name: 'aviso_ti', template_language: 'pt_BR', app_base_url: ''
    });
  });

  it('shows the Meta refusal and keeps the form', async () => {
    const err = { error: { error: { message: 'A Meta recusou o token ou o Phone Number ID: Invalid OAuth access token' } } };
    const api = { getWhatsAppConfig: vi.fn().mockReturnValue(of(CONFIG)), saveWhatsAppConfig: vi.fn().mockReturnValue(throwError(() => err)) };
    const fixture = await mount(WhatsAppConfigComponent, provide(api));
    fixture.componentInstance.save();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[role="alert"]').textContent).toContain('A Meta recusou');
    expect(fixture.componentInstance.config()).not.toBeNull();
  });
});

describe('SlackConfigComponent', () => {
  const CONFIG = {
    enabled: false, bot_token: '', signing_secret: '', app_base_url: '', bot_name: null, team_name: null,
    events_path: '/api/v1/integrations/slack/events'
  };
  const provide = (api: object) => [{ provide: NotificationsAdminService, useValue: api }];

  it('shows the Request URL, masks secrets and saves what the admin typed', async () => {
    const api = {
      getSlackConfig: vi.fn().mockReturnValue(of({ ...CONFIG, bot_token: '********', signing_secret: '********', bot_name: 'gti_bot', team_name: 'Empresa' })),
      saveSlackConfig: vi.fn().mockReturnValue(of({ ...CONFIG, enabled: true, bot_token: '********', signing_secret: '********' }))
    };
    const fixture = await mount(SlackConfigComponent, provide(api));
    expect(fixture.nativeElement.textContent).toContain('gti_bot em Empresa');
    expect(fixture.nativeElement.querySelector('[data-testid="sl-webhook"]').textContent).toContain('/api/v1/integrations/slack/events');
    expect((fixture.nativeElement.querySelector('[data-testid="sl-token"]') as HTMLInputElement).type).toBe('password');

    const c = fixture.componentInstance;
    c.config.update((cfg) => ({ ...cfg!, enabled: true, bot_token: 'xoxb-NEW', app_base_url: ' https://ti.x ' }));
    c.save();
    expect(api.saveSlackConfig).toHaveBeenCalledWith({ enabled: true, bot_token: 'xoxb-NEW', signing_secret: '********', app_base_url: 'https://ti.x' });
    expect(c.config()!.bot_token).toBe('********');
  });

  it('shows the API validation message and reports load failures', async () => {
    const err = { error: { error: { message: 'O Slack recusou o token: invalid_auth' } } };
    const api = { getSlackConfig: vi.fn().mockReturnValue(of(CONFIG)), saveSlackConfig: vi.fn().mockReturnValue(throwError(() => err)) };
    const fixture = await mount(SlackConfigComponent, provide(api));
    fixture.componentInstance.save();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[role="alert"]').textContent).toContain('invalid_auth');

    TestBed.resetTestingModule();
    const broken = await mount(SlackConfigComponent, provide({ getSlackConfig: vi.fn().mockReturnValue(throwError(() => new Error('x'))) }));
    expect(broken.nativeElement.querySelector('[role="alert"]').textContent).toContain('Não foi possível carregar');
  });
});
