import { TestBed } from '@angular/core/testing';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';
import { of, throwError } from 'rxjs';
import { ChannelLinkInfo, NotificationsService } from '../../core/services/notifications.service';
import { NotificationsAdminService } from '../../core/services/notifications-admin.service';
import { MyChannelsComponent, minutesLeft } from './preferences/my-channels.component';
import { TelegramConfigComponent } from './admin/telegram-config.component';

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
