import { Component, OnInit, OnDestroy, inject, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterOutlet, Router, NavigationEnd } from '@angular/router';
import { MatDrawerMode, MatSidenav, MatSidenavModule } from '@angular/material/sidenav';
import { BreakpointObserver, Breakpoints } from '@angular/cdk/layout';
import { Subscription, filter } from 'rxjs';

import { HeaderComponent } from '../header/header.component';
import { SidebarComponent } from '../sidebar/sidebar.component';
import { AuthService } from '../../auth/auth.service';

@Component({
  selector: 'app-shell',
  standalone: true,
  imports: [
    CommonModule,
    RouterOutlet,
    MatSidenavModule,
    HeaderComponent,
    SidebarComponent
  ],
  template: `
    <mat-sidenav-container class="sidenav-container">
      <mat-sidenav 
        #sidenav 
        [mode]="sidenavMode" 
        [opened]="sidenavOpened" 
        class="sidenav"
        (closed)="onSidenavClosed()">
        <app-sidebar></app-sidebar>
      </mat-sidenav>
      
      <mat-sidenav-content class="sidenav-content">
        <app-header (toggleSidenav)="toggleSidenav()"></app-header>
        <main class="main-content">
          <router-outlet></router-outlet>
        </main>
      </mat-sidenav-content>
    </mat-sidenav-container>
  `,
  styles: [`
    .sidenav-container {
      height: 100vh;
      background-color: #f8fafc;
    }
    
    .sidenav {
      width: 260px;
      background-color: #ffffff;
      border-right: 1px solid #e2e8f0;
      box-shadow: 2px 0 8px rgba(0, 0, 0, 0.02);
    }
    
    .sidenav-content {
      display: flex;
      flex-direction: column;
      height: 100vh;
      overflow: hidden;
    }

    .main-content {
      flex: 1;
      padding: 24px 32px;
      overflow-y: auto;
      box-sizing: border-box;
      background-color: #f8fafc;

      @media (max-width: 768px) {
        padding: 16px;
      }
    }
  `]
})
export class ShellComponent implements OnInit, OnDestroy {
  @ViewChild('sidenav') sidenav?: MatSidenav;

  authService = inject(AuthService);
  private router = inject(Router);
  private breakpointObserver = inject(BreakpointObserver);

  isMobile = false;
  sidenavMode: MatDrawerMode = 'side';
  sidenavOpened = true;

  private subscriptions = new Subscription();

  ngOnInit() {
    // Password change check
    this.subscriptions.add(
      this.authService.currentUser$.subscribe((user) => {
        if (user?.must_change_password) {
          this.router.navigate(['/change-password']);
        }
      })
    );

    // Responsive breakpoint detection
    this.subscriptions.add(
      this.breakpointObserver
        .observe([Breakpoints.Handset, Breakpoints.TabletPortrait])
        .subscribe((result) => {
          this.isMobile = result.matches;
          if (this.isMobile) {
            this.sidenavMode = 'over';
            this.sidenavOpened = false;
          } else {
            this.sidenavMode = 'side';
            this.sidenavOpened = true;
          }
        })
    );

    // Auto-close on mobile when navigating
    this.subscriptions.add(
      this.router.events
        .pipe(filter((event) => event instanceof NavigationEnd))
        .subscribe(() => {
          if (this.isMobile && this.sidenav) {
            this.sidenav.close();
          }
        })
    );
  }

  toggleSidenav(): void {
    if (this.sidenav) {
      this.sidenav.toggle();
    }
  }

  onSidenavClosed(): void {
    if (this.isMobile) {
      this.sidenavOpened = false;
    }
  }

  ngOnDestroy() {
    this.subscriptions.unsubscribe();
  }
}
