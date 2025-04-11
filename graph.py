import matplotlib.pyplot as plt
import numpy as np

# Data for comparison
features = ['Priority Levels', 'Team Collaboration', 'Streak Tracking', 'Study Plans', 'Scheduling', 'Task Completion Rate', 'Time Management']
tasklypro_scores = [5, 4, 4, 4, 4, 4.5, 4.5]  # Scores out of 5 based on features and efficiency
traditional_scores = [1, 0, 0, 1, 1, 2, 2]  # Scores out of 5 for traditional methods

# Set the positions and width for the bars
x = np.arange(len(features))
width = 0.35

# Create the figure and axis
fig, ax = plt.subplots(figsize=(10, 6))

# Plot bars
bars1 = ax.bar(x - width/2, tasklypro_scores, width, label='TasklyPro', color='skyblue')
bars2 = ax.bar(x + width/2, traditional_scores, width, label='Traditional Methods', color='lightcoral')

# Add labels, title, and customize the plot
ax.set_ylabel('Score (out of 5)')
ax.set_title('Comparison: TasklyPro vs Traditional Methods')
ax.set_xticks(x)
ax.set_xticklabels(features, rotation=45, ha='right')
ax.legend()

# Add value labels on top of each bar
for bars in [bars1, bars2]:
    for bar in bars:
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height,
                f'{height:.1f}',
                ha='center', va='bottom')

# Adjust layout to prevent label cutoff
plt.tight_layout()

# Save the graph as an image (optional)
plt.savefig('tasklypro_vs_traditional.png')

# Display the graph
plt.show()