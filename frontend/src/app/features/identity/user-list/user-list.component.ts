import { Component, OnInit, inject, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatTableModule } from '@angular/material/table';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { IdentityService, User } from '../../../core/services/identity.service';
import { UserDialogComponent } from './user-dialog.component';

@Component({
  selector: 'app-user-list',
  standalone: true,
  imports: [
    CommonModule,
    MatTableModule,
    MatButtonModule,
    MatIconModule,
    MatDialogModule,
    MatSnackBarModule
  ],
  templateUrl: './user-list.component.html',
  styleUrls: ['./user-list.component.scss']
})
export class UserList implements OnInit {
  private identityService = inject(IdentityService);
  private dialog = inject(MatDialog);
  private snackBar = inject(MatSnackBar);
  private cdr = inject(ChangeDetectorRef);

  displayedColumns: string[] = ['email', 'roles', 'admin', 'status', 'actions'];
  dataSource: User[] = [];

  ngOnInit(): void {
    this.loadData();
  }

  loadData() {
    this.identityService.getUsers().subscribe({
      next: (data) => {
        this.dataSource = data;
        this.cdr.markForCheck();
      },
      error: (err) => {
        this.snackBar.open(err.error?.detail || 'Erro ao carregar usuários', 'Fechar', { duration: 3000 });
      }
    });
  }

  openDialog(user?: User) {
    const dialogRef = this.dialog.open(UserDialogComponent, {
      width: '500px',
      data: user || null
    });

    dialogRef.afterClosed().subscribe(result => {
      if (result) {
        if (user) {
          // Remove password when updating to not break the API if empty
          delete result.password;
          this.identityService.updateUser(user.id, result).subscribe({
            next: () => this.loadData(),
            error: (err) => this.snackBar.open(err.error?.detail || 'Erro ao salvar', 'Fechar', { duration: 3000 })
          });
        } else {
          result.must_change_password = true;
          this.identityService.createUser(result).subscribe({
            next: () => this.loadData(),
            error: (err) => this.snackBar.open(err.error?.detail || 'Erro ao salvar', 'Fechar', { duration: 3000 })
          });
        }
      }
    });
  }

  resetPassword(id: string) {
    if (confirm('Tem certeza que deseja resetar a senha deste usuário para "temporaria-123"?')) {
      this.identityService.resetPassword(id, 'temporaria-123').subscribe(() => {
        this.snackBar.open('Senha resetada com sucesso.', 'Fechar', { duration: 3000 });
        this.loadData();
      });
    }
  }

  deleteUser(id: string) {
    if (confirm('Tem certeza que deseja inativar/remover este usuário?')) {
      this.identityService.deleteUser(id).subscribe(() => this.loadData());
    }
  }
}
