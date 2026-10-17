import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { BehaviorSubject } from 'rxjs';
import { AuthService } from '../auth/auth.service';
import { NotificationsService } from './notifications.service';

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  close = vi.fn();
  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }
}

describe('NotificationsService', () => {
  let http: HttpTestingController;
  let user$: BehaviorSubject<unknown>;

  function setup(user: unknown) {
    user$ = new BehaviorSubject<unknown>(user);
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: AuthService, useValue: { currentUser$: user$, token: 'ACCESS-TOKEN-SECRET' } }
      ]
    });
    http = TestBed.inject(HttpTestingController);
    return TestBed.inject(NotificationsService);
  }

  beforeEach(() => {
    FakeWebSocket.instances = [];
    vi.stubGlobal('WebSocket', FakeWebSocket);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it('connects with a short-lived ticket and never puts the access token in the URL', () => {
    setup({ id: 'u1' });

    http.expectOne('/api/v1/notifications/ws-ticket').flush({ ticket: 'TICKET-123' });

    expect(FakeWebSocket.instances).toHaveLength(1);
    const url = FakeWebSocket.instances[0].url;
    expect(url).toContain('/api/v1/notifications/ws?ticket=TICKET-123');
    expect(url).not.toContain('ACCESS-TOKEN-SECRET');
    expect(url).not.toContain('token=');
  });

  it('does not open a socket without a logged user', () => {
    setup(null);
    http.expectNone('/api/v1/notifications/ws-ticket');
    expect(FakeWebSocket.instances).toHaveLength(0);
  });

  it('emits pushed notifications and signals reconnection so lists reload from REST', () => {
    const service = setup({ id: 'u1' });
    const received: string[] = [];
    let reconnects = 0;
    service.newNotification$.subscribe((n) => received.push(n.title));
    service.reconnected$.subscribe(() => reconnects++);

    http.expectOne('/api/v1/notifications/ws-ticket').flush({ ticket: 't' });
    const socket = FakeWebSocket.instances[0];
    socket.onopen?.();
    socket.onmessage?.({ data: JSON.stringify({ type: 'NEW_NOTIFICATION', payload: { title: 'Olá' } }) });
    socket.onmessage?.({ data: 'não é json' });

    expect(received).toEqual(['Olá']);
    expect(reconnects).toBe(1);
  });

  it('reconnects with a NEW ticket after the socket closes, with backoff', () => {
    vi.useFakeTimers();
    setup({ id: 'u1' });
    http.expectOne('/api/v1/notifications/ws-ticket').flush({ ticket: 'first' });

    FakeWebSocket.instances[0].onclose?.();
    http.expectNone('/api/v1/notifications/ws-ticket');
    vi.advanceTimersByTime(2_000);

    http.expectOne('/api/v1/notifications/ws-ticket').flush({ ticket: 'second' });
    expect(FakeWebSocket.instances[1].url).toContain('ticket=second');

    FakeWebSocket.instances[1].onclose?.();
    vi.advanceTimersByTime(2_000);
    http.expectNone('/api/v1/notifications/ws-ticket'); // o atraso dobrou (4 s)
    vi.advanceTimersByTime(2_000);
    http.expectOne('/api/v1/notifications/ws-ticket').flush({ ticket: 'third' });
  });

  it('stops reconnecting after logout', () => {
    vi.useFakeTimers();
    setup({ id: 'u1' });
    http.expectOne('/api/v1/notifications/ws-ticket').flush({ ticket: 'first' });
    FakeWebSocket.instances[0].onclose?.();

    user$.next(null);
    vi.advanceTimersByTime(120_000);
    http.expectNone('/api/v1/notifications/ws-ticket');
  });

  it('lists with filters and omits empty ones', () => {
    const service = setup(null);
    service.list({ is_read: false, type: '', date_from: '2026-10-01', limit: 25, offset: 0 }).subscribe();

    const req = http.expectOne((r) => r.url === '/api/v1/notifications');
    expect(req.request.params.get('is_read')).toBe('false');
    expect(req.request.params.get('date_from')).toBe('2026-10-01');
    expect(req.request.params.has('type')).toBe(false);
    req.flush([]);
  });

  it('saves only the editable preference fields', () => {
    const service = setup(null);
    service
      .savePrefs({
        channels_disabled: ['email'], categories_disabled: [], quiet_enabled: true, quiet_start: '20:00',
        quiet_end: '07:00', critical_bypass: true, timezone: 'America/Fortaleza', available_channels: ['email']
      })
      .subscribe();

    const req = http.expectOne('/api/v1/notifications/prefs');
    expect(req.request.method).toBe('PUT');
    expect(Object.keys(req.request.body).sort()).toEqual(
      ['categories_disabled', 'channels_disabled', 'critical_bypass', 'quiet_enabled', 'quiet_end', 'quiet_start']
    );
    req.flush({});
  });
});
