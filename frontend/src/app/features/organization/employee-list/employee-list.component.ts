import { Component, OnInit, inject, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatTableModule } from '@angular/material/table';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { OrganizationService, Employee } from '../../../core/services/organization.service';
import { EmployeeDialogComponent } from './employee-dialog.component';

@Component({
  selector: 'app-employee-list',
  standalone: true,
  imports: [
    CommonModule,
    MatTableModule,
    MatButtonModule,
    MatIconModule,
    MatDialogModule,
    MatSnackBarModule
  ],
  templateUrl: './employee-list.component.html',
  styleUrls: ['./employee-list.component.scss']
})
export class EmployeeList implements OnInit {
  private orgService = inject(OrganizationService);
  private dialog = inject(MatDialog);
  private snackBar = inject(MatSnackBar);
  private cdr = inject(ChangeDetectorRef);

  displayedColumns: string[] = ['sector', 'registration', 'name', 'phone', 'job_title', 'status', 'actions'];
  dataSource: Employee[] = [];

  ngOnInit(): void {
    this.loadData();
  }

  loadData() {
    this.orgService.getEmployees().subscribe({
      next: (data) => {
        this.dataSource = data;
        this.cdr.markForCheck();
      },
      error: (err) => {
        this.snackBar.open(err.error?.detail || 'Erro ao carregar colaboradores', 'Fechar', { duration: 3000 });
      }
    });
  }

  openDialog(employee?: Employee) {
    const dialogRef = this.dialog.open(EmployeeDialogComponent, {
      width: '400px',
      data: employee || null
    });

    dialogRef.afterClosed().subscribe(result => {
      if (result) {
        if (employee) {
          this.orgService.updateEmployee(employee.id, result).subscribe({
            next: () => {
              this.snackBar.open('Colaborador atualizado com sucesso', 'Fechar', { duration: 3000 });
              this.loadData();
            },
            error: (err) => {
              this.snackBar.open(err.error?.detail || 'Erro ao atualizar colaborador', 'Fechar', { duration: 4000 });
            }
          });
        } else {
          this.orgService.createEmployee(result).subscribe({
            next: () => {
              this.snackBar.open('Colaborador criado com sucesso', 'Fechar', { duration: 3000 });
              this.loadData();
            },
            error: (err) => {
              this.snackBar.open(err.error?.detail || 'Erro ao criar colaborador', 'Fechar', { duration: 4000 });
            }
          });
        }
      }
    });
  }

  deleteEmployee(id: string) {
    if (confirm('Tem certeza que deseja inativar/remover este colaborador?')) {
      this.orgService.deleteEmployee(id).subscribe({
        next: () => {
          this.snackBar.open('Colaborador inativado com sucesso', 'Fechar', { duration: 3000 });
          this.loadData();
        },
        error: (err) => {
          this.snackBar.open(err.error?.detail || 'Erro ao inativar colaborador', 'Fechar', { duration: 4000 });
        }
      });
    }
  }
}
