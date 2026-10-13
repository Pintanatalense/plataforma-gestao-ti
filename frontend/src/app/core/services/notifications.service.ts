import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
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

@Injectable({
  providedIn: 'root'
})
export class NotificationsService {
  private http = inject(HttpClient);
  private authService = inject(AuthService);

  private ws: WebSocket | null = null;
  private newNotificationSubject = new Subject<Notification>();
  public newNotification$ = this.newNotificationSubject.asObservable();

  private apiUrl = '/api/v1/notifications';

  constructor() {
    this.authService.currentUser$.subscribe(user => {
      if (user) {
        this.connectWs();
      } else {
        this.disconnectWs();
      }
    });
  }

  private connectWs() {
    if (this.ws) return;

    const token = this.authService.token;
    if (!token) return;

    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProtocol}//${window.location.host}/api/v1/notifications/ws?token=${token}`;

    try {
      this.ws = new WebSocket(wsUrl);

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'NEW_NOTIFICATION') {
            this.newNotificationSubject.next(data.payload);
          }
        } catch (e) {
          console.error('Failed to parse WS message', e);
        }
      };

      this.ws.onclose = () => {
        this.ws = null;
      };
    } catch (err) {
      console.warn('Could not establish WebSocket connection', err);
    }
  }

  private disconnectWs() {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  getNotifications(limit: number = 50, offset: number = 0): Observable<Notification[]> {
    return this.http.get<Notification[]>(`${this.apiUrl}?limit=${limit}&offset=${offset}`);
  }

  markAsRead(notificationId: string): Observable<Notification> {
    return this.http.post<Notification>(`${this.apiUrl}/${notificationId}/read`, {});
  }

  markAllAsRead(): Observable<any> {
    return this.http.post(`${this.apiUrl}/read-all`, {});
  }
}
