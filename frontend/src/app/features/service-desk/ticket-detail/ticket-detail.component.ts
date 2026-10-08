import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterModule } from '@angular/router';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatCardModule } from '@angular/material/card';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatChipsModule } from '@angular/material/chips';
import { MatDividerModule } from '@angular/material/divider';
import { Ticket, TicketService } from '../ticket.service';
import { AuthService } from '../../../core/auth/auth.service';

@Component({
  selector: 'app-ticket-detail',
  standalone: true,
  imports: [
    CommonModule, 
    ReactiveFormsModule, 
    RouterModule,
    MatButtonModule, 
    MatIconModule, 
    MatInputModule, 
    MatCardModule,
    MatCheckboxModule,
    MatChipsModule,
    MatDividerModule
  ],
  templateUrl: './ticket-detail.component.html',
  styleUrls: ['./ticket-detail.component.scss']
})
export class TicketDetailComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private ticketService = inject(TicketService);
  public authService = inject(AuthService);
  private fb = inject(FormBuilder);

  ticket: Ticket | null = null;
  messageForm: FormGroup;
  isTechnician = false;

  constructor() {
    this.messageForm = this.fb.group({
      message: ['', Validators.required],
      is_internal: [false]
    });
  }

  ngOnInit() {
    this.isTechnician = this.authService.hasPermission('service_desk.tickets.read_internal') || !!this.authService.currentUserValue?.is_admin;
    
    this.route.paramMap.subscribe(params => {
      const id = params.get('id');
      if (id) {
        this.loadTicket(id);
      }
    });
  }

  loadTicket(id: string) {
    this.ticketService.getTicket(id).subscribe({
      next: (data) => this.ticket = data,
      error: (err) => console.error(err)
    });
  }

  sendMessage() {
    if (this.messageForm.invalid || !this.ticket) return;

    const { message, is_internal } = this.messageForm.value;
    
    this.ticketService.addInteraction(this.ticket.id, message, is_internal).subscribe({
      next: (interaction) => {
        this.ticket?.interactions.push(interaction);
        this.messageForm.reset({ is_internal: false });
        this.scrollToBottom();
      },
      error: (err) => console.error(err)
    });
  }

  closeTicket() {
    if (!this.ticket) return;
    this.ticketService.updateTicket(this.ticket.id, { status: 'CLOSED' }).subscribe({
      next: (updatedTicket) => this.ticket = updatedTicket,
      error: (err) => console.error(err)
    });
  }

  isMyMessage(authorId: string): boolean {
    return this.authService.currentUserValue?.id === authorId;
  }

  private scrollToBottom() {
    setTimeout(() => {
      const container = document.getElementById('chat-container');
      if (container) {
        container.scrollTop = container.scrollHeight;
      }
    }, 100);
  }
}
