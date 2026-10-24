import { Component, input } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { provideRouter } from '@angular/router';
import { AuthService } from '../../core/auth/auth.service';
import { ChannelsComponent } from '../notifications/admin/channels.component';
import { SlackConfigComponent } from '../notifications/admin/slack-config.component';
import { TelegramConfigComponent } from '../notifications/admin/telegram-config.component';
import { WhatsAppConfigComponent } from '../notifications/admin/whatsapp-config.component';
import { ChannelsPageComponent } from './channels-page.component';
import { EmailConfigComponent } from './email-config.component';

@Component({ selector: 'app-channels', standalone: true, template: '<i data-testid="status">{{ only() }}</i>' })
class StubStatus { only = input<string | null>(null); }
@Component({ selector: 'app-email-config', standalone: true, template: '<i data-testid="email-form"></i>' })
class StubEmail {}
@Component({ selector: 'app-whatsapp-config', standalone: true, template: '<i data-testid="whatsapp-form"></i>' })
class StubWhatsApp {}
@Component({ selector: 'app-telegram-config', standalone: true, template: '' })
class StubTelegram {}
@Component({ selector: 'app-slack-config', standalone: true, template: '' })
class StubSlack {}

async function mount(permissions: string[]) {
  await TestBed.configureTestingModule({
    imports: [ChannelsPageComponent],
    providers: [
      provideNoopAnimations(),
      provideRouter([]),
      { provide: AuthService, useValue: { hasPermission: (p: string) => permissions.includes(p) } }
    ]
  })
    .overrideComponent(ChannelsPageComponent, {
      remove: { imports: [ChannelsComponent, EmailConfigComponent, WhatsAppConfigComponent, TelegramConfigComponent, SlackConfigComponent] },
      add: { imports: [StubStatus, StubEmail, StubWhatsApp, StubTelegram, StubSlack] }
    })
    .compileComponents();
  const fixture = TestBed.createComponent(ChannelsPageComponent);
  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
  return fixture;
}

const labels = (root: HTMLElement) =>
  Array.from(root.querySelectorAll('[role="tab"]')).map((t) => (t.textContent ?? '').trim());

describe('ChannelsPageComponent', () => {
  it('shows the four tabs, in order, to someone who manages notifications', async () => {
    const fixture = await mount(['notifications.manage']);
    expect(labels(fixture.nativeElement)).toEqual(['E-mail', 'WhatsApp', 'Telegram', 'Slack']);
  });

  it('the e-mail tab is the only one for system.backup.manage, without the status card or the rules link', async () => {
    const fixture = await mount(['system.backup.manage']);
    const el = fixture.nativeElement as HTMLElement;
    expect(labels(el)).toEqual(['E-mail']);
    expect(el.querySelector('[data-testid="email-form"]')).toBeTruthy();
    expect(el.querySelector('[data-testid="status"]')).toBeNull(); // o painel de saúde exige notifications.manage
    expect(el.querySelector('[data-testid="rules-link"]')).toBeNull();
  });

  it('the e-mail tab for a manager shows the e-mail status card and links to the rules', async () => {
    const fixture = await mount(['notifications.manage']);
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('[data-testid="status"]')?.textContent).toBe('email');
    expect(el.querySelector('[data-testid="rules-link"]')?.getAttribute('href')).toBe('/notifications/admin');
  });

  it('shows no tab at all without any permission', async () => {
    const fixture = await mount([]);
    expect(labels(fixture.nativeElement)).toEqual([]);
  });
});
