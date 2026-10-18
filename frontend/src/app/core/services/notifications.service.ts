import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable, Subject } from 'rxjs';
import { AuthService } from '../auth/auth.service';

export interface Notification {
  id: string;
  user_id: string;
  title: string;
  message: string;
  type: string;
  is_read: boolean;
  entity_type?: string;
  entity_id?: string;
  created_at: string;
}

export interface NotificationFilters {
  is_read?: boolean;
  type?: string;
  date_from?: string;
  date_to?: string;
  limit?: number;
  offset?: number;
}

export interface NotificationPrefs {
  channels_disabled: string[];
  categories_disabled: string[];
  quiet_enabled: boolean;
  quiet_start: string;
  quiet_end: string;
  critical_bypass: boolean;
  timezone?: string;
  available_channels?: string[];
  available_categories?: string[];
}

export interface ChannelLinkInfo {
  channel: string;
  label: string;
  available: boolean;
  bot_username: string | null;
  bot_name?: string | null;
  display_phone?: string | null;
  linked: boolean;
  linked_at: string | null;
}

export interface LinkCode {
  code: string;
  expires_at: string;
  command: string;
  deep_link: string | null;
}

const RECONNECT_MIN_MS = 2_000;
const RECONNECT_MAX_MS = 60_000;

@Injectable({
  providedIn: 'root'
})
export class NotificationsService {
  private http = inject(HttpClient);
  private authService = inject(AuthService);

  private ws: WebSocket | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectDelay = RECONNECT_MIN_MS;
  private wantConnection = false;

  private newNotificationSubject = new Subject<Notification>();
  public newNotification$ = this.newNotificationSubject.asObservable();
  /** Emite quando o WebSocket (re)conecta: quem exibe a lista deve recarregar pela REST. */
  private reconnectedSubject = new Subject<void>();
  public reconnected$ = this.reconnectedSubject.asObservable();

  private apiUrl = '/api/v1/notifications';

  constructor() {
    this.authService.currentUser$.subscribe(user => {
      if (user) {
        this.wantConnection = true;
        this.connectWs();
      } else {
        this.wantConnection = false;
        this.disconnectWs();
      }
    });
  }

  /** O token de acesso nunca vai na URL (apareceria no log do Nginx): troca por um ticket de 60 s. */
  private connectWs(): void {
    if (this.ws || !this.authService.token) return;

    this.http.post<{ ticket: string }>(`${this.apiUrl}/ws-ticket`, {}).subscribe({
      next: ({ ticket }) => this.openSocket(ticket),
      error: () => this.scheduleReconnect()
    });
  }

  private openSocket(ticket: string): void {
    if (this.ws || !this.wantConnection) return;
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProtocol}//${window.location.host}${this.apiUrl}/ws?ticket=${encodeURIComponent(ticket)}`;

    try {
      const socket = new WebSocket(wsUrl);
      this.ws = socket;

      socket.onopen = () => {
        this.reconnectDelay = RECONNECT_MIN_MS;
        this.reconnectedSubject.next();
      };
      socket.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'NEW_NOTIFICATION') {
            this.newNotificationSubject.next(data.payload);
          }
        } catch (e) {
          console.error('Failed to parse WS message', e);
        }
      };
      socket.onclose = () => {
        if (this.ws === socket) this.ws = null;
        this.scheduleReconnect();
      };
    } catch (err) {
      console.warn('Could not establish WebSocket connection', err);
      this.scheduleReconnect();
    }
  }

  private scheduleReconnect(): void {
    if (!this.wantConnection || this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connectWs();
    }, this.reconnectDelay);
    this.reconnectDelay = Math.min(this.reconnectDelay * 2, RECONNECT_MAX_MS);
  }

  private disconnectWs(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.reconnectDelay = RECONNECT_MIN_MS;
    if (this.ws) {
      const socket = this.ws;
      this.ws = null;
      socket.close();
    }
  }

  getNotifications(limit: number = 50, offset: number = 0): Observable<Notification[]> {
    return this.list({ limit, offset });
  }

  list(filters: NotificationFilters = {}): Observable<Notification[]> {
    let params = new HttpParams();
    for (const [key, value] of Object.entries(filters)) {
      if (value !== undefined && value !== null && value !== '') {
        params = params.set(key, String(value));
      }
    }
    return this.http.get<Notification[]>(this.apiUrl, { params });
  }

  unreadCount(): Observable<{ count: number }> {
    return this.http.get<{ count: number }>(`${this.apiUrl}/unread-count`);
  }

  markAsRead(notificationId: string): Observable<Notification> {
    return this.http.post<Notification>(`${this.apiUrl}/${notificationId}/read`, {});
  }

  markAllAsRead(): Observable<any> {
    return this.http.post(`${this.apiUrl}/read-all`, {});
  }

  myChannels(): Observable<{ channels: ChannelLinkInfo[] }> {
    return this.http.get<{ channels: ChannelLinkInfo[] }>(`${this.apiUrl}/channels`);
  }

  createLinkCode(channel: string): Observable<LinkCode> {
    return this.http.post<LinkCode>(`${this.apiUrl}/channels/${channel}/link-code`, {});
  }

  unlinkChannel(channel: string): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}/channels/${channel}`);
  }

  getPrefs(): Observable<NotificationPrefs> {
    return this.http.get<NotificationPrefs>(`${this.apiUrl}/prefs`);
  }

  savePrefs(prefs: NotificationPrefs): Observable<NotificationPrefs> {
    const { channels_disabled, categories_disabled, quiet_enabled, quiet_start, quiet_end, critical_bypass } = prefs;
    return this.http.put<NotificationPrefs>(`${this.apiUrl}/prefs`, {
      channels_disabled, categories_disabled, quiet_enabled, quiet_start, quiet_end, critical_bypass
    });
  }
}
