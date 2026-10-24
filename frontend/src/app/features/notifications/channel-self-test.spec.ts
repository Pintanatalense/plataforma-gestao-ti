import { TestBed } from '@angular/core/testing';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';
import { of, throwError } from 'rxjs';
import { NotificationsAdminService } from '../../core/services/notifications-admin.service';
import { ChannelSelfTestComponent } from './admin/channel-self-test.component';
import { SlackConfigComponent } from './admin/slack-config.component';
import { TelegramConfigComponent } from './admin/telegram-config.component';

async function mount<T>(component: new () => T, api: object, inputs: Record<string, unknown> = {}) {
  await TestBed.configureTestingModule({
    imports: [component as never],
    providers: [provideAnimationsAsync(), { provide: NotificationsAdminService, useValue: api }]
  }).compileComponents();
  const fixture = TestBed.createComponent(component);
  for (const [name, value] of Object.entries(inputs)) fixture.componentRef.setInput(name, value);
  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
  return fixture;
}
const q = (f: { nativeElement: HTMLElement }, id: string) => f.nativeElement.querySelector(`[data-testid="${id}"]`) as HTMLElement | null;

describe('ChannelSelfTestComponent', () => {
  it('asks the API to test the given channel and shows the result', async () => {
    const api = { testSendToMyself: vi.fn().mockReturnValue(of({ ok: true, detail: 'Mensagem enviada para a sua conta no Telegram.' })) };
    const f = await mount(ChannelSelfTestComponent, api, { channel: 'telegram' });
    (q(f, 'self-test-send') as HTMLButtonElement).click();
    f.detectChanges();
    expect(api.testSendToMyself).toHaveBeenCalledWith('telegram');
    expect(q(f, 'self-test-result')?.textContent).toContain('Mensagem enviada');
  });

  it('shows the server explanation (for example, not linked yet) instead of failing silently', async () => {
    const err = { error: { error: { message: 'Sua conta ainda não está vinculada ao Slack. Vincule em Notificações > Minhas preferências e teste de novo.' } } };
    const api = { testSendToMyself: vi.fn().mockReturnValue(throwError(() => err)) };
    const f = await mount(ChannelSelfTestComponent, api, { channel: 'slack' });
    (q(f, 'self-test-send') as HTMLButtonElement).click();
    f.detectChanges();
    expect(q(f, 'self-test-result')?.textContent).toContain('ainda não está vinculada');
    expect((q(f, 'self-test-send') as HTMLButtonElement).disabled).toBe(false);
  });
});

describe('the test box inside the channel cards', () => {
  const TG = { enabled: true, bot_token: '********', bot_username: 'gti_bot', app_base_url: '' };
  const SL = { enabled: true, bot_token: '********', signing_secret: '********', app_base_url: '', bot_name: 'gti', team_name: 'Empresa', events_path: '/api/v1/integrations/slack/events' };

  it('Telegram shows it only when the channel is enabled and a bot is configured', async () => {
    const on = await mount(TelegramConfigComponent, { getTelegramConfig: vi.fn().mockReturnValue(of(TG)) });
    expect(q(on, 'self-test')).toBeTruthy();
    TestBed.resetTestingModule();
    const off = await mount(TelegramConfigComponent, { getTelegramConfig: vi.fn().mockReturnValue(of({ ...TG, enabled: false })) });
    expect(q(off, 'self-test')).toBeNull();
  });

  it('Slack shows it only when the channel is enabled and the bot is known', async () => {
    const on = await mount(SlackConfigComponent, { getSlackConfig: vi.fn().mockReturnValue(of(SL)) });
    expect(q(on, 'self-test')).toBeTruthy();
    TestBed.resetTestingModule();
    const off = await mount(SlackConfigComponent, { getSlackConfig: vi.fn().mockReturnValue(of({ ...SL, bot_name: null })) });
    expect(q(off, 'self-test')).toBeNull();
  });
});
